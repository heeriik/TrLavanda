// Package feed mantiene al día los datos del gateway.
//
//  1. Al arrancar descarga por HTTP la última versión de scores (factors), prices y universe (ingest).
//  2. Escucha Kafka (scores.published, data.updated) para enterarse al momento de las nuevas.
//  3. Cada cierto tiempo vuelve a preguntar por HTTP (red de seguridad: el gateway no confirma
//     mensajes, así que si una descarga falla, el evento no se repite).
//
// Cada versión se descarga entera, se comprueba su sha256 y solo entonces se construye un
// data.Data nuevo que sustituye al anterior de golpe.
package feed

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/twmb/franz-go/pkg/kgo"

	"github.com/heeriik/TrLavanda/services/gateway/internal/contracts"
	"github.com/heeriik/TrLavanda/services/gateway/internal/data"
)

// Datasets que usa el gateway -> archivos que necesita de cada uno.
var files = map[string][]string{
	"scores":   {"factor_scores.parquet"},
	"prices":   {"prices.parquet", "coverage_report.json"},
	"universe": {"sp500_current.parquet"},
}

type manifest struct {
	Dataset string `json:"dataset"`
	Version string `json:"version"`
	Files   map[string]struct {
		SHA256 string `json:"sha256"`
	} `json:"files"`
}

type Feed struct {
	c         *contracts.Contracts
	owners    map[string]string // dataset -> URL base del servicio dueño
	benchmark string
	onData    func(*data.Data)
	http      *http.Client
	log       *slog.Logger

	mu       sync.Mutex
	scores   *data.Scores
	prices   *data.Prices
	universe *data.Universe
}

func New(c *contracts.Contracts, ingestURL, factorsURL, benchmark string, onData func(*data.Data), log *slog.Logger) *Feed {
	ingestURL, factorsURL = strings.TrimRight(ingestURL, "/"), strings.TrimRight(factorsURL, "/")
	return &Feed{
		c:         c,
		owners:    map[string]string{"scores": factorsURL, "prices": ingestURL, "universe": ingestURL},
		benchmark: benchmark,
		onData:    onData,
		http:      &http.Client{Timeout: 5 * time.Minute},
		log:       log,
	}
}

// Versions: versión cargada de cada dataset (para /healthz).
func (f *Feed) Versions() map[string]string {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := map[string]string{}
	if f.scores != nil {
		out["scores"] = f.scores.Version
	}
	if f.prices != nil {
		out["prices"] = f.prices.Version
	}
	if f.universe != nil {
		out["universe"] = f.universe.Version
	}
	return out
}

func (f *Feed) current(ds string) string { return f.Versions()[ds] }

func (f *Feed) get(ctx context.Context, url string) ([]byte, int, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, 0, err
	}
	res, err := f.http.Do(req)
	if err != nil {
		return nil, 0, err
	}
	defer res.Body.Close()
	b, err := io.ReadAll(res.Body)
	if err == nil && res.StatusCode != http.StatusOK {
		err = fmt.Errorf("GET %s: %s", url, res.Status)
	}
	return b, res.StatusCode, err
}

// Load descarga la versión cuyo manifiesto está en `url` (si es más nueva que la cargada).
func (f *Feed) Load(ctx context.Context, url string) error {
	b, _, err := f.get(ctx, url)
	if err != nil {
		return err
	}
	var m manifest
	if err := json.Unmarshal(b, &m); err != nil {
		return fmt.Errorf("manifiesto %s: %w", url, err)
	}
	names, ok := files[m.Dataset]
	if !ok {
		return nil // un dataset que el gateway no usa (p. ej. edgar)
	}
	if cur := f.current(m.Dataset); cur >= m.Version { // ids ordenables por fecha
		return nil
	}
	t0 := time.Now()
	blobs := map[string][]byte{}
	for _, name := range names {
		info, ok := m.Files[name]
		if !ok {
			return fmt.Errorf("%s/%s no tiene %s", m.Dataset, m.Version, name)
		}
		b, _, err := f.get(ctx, url+"/files/"+name)
		if err != nil {
			return err
		}
		if sum := sha256.Sum256(b); hex.EncodeToString(sum[:]) != info.SHA256 {
			return fmt.Errorf("%s/%s/%s: sha256 no coincide (descarga corrupta)", m.Dataset, m.Version, name)
		}
		blobs[name] = b
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	switch m.Dataset {
	case "scores":
		s, err := data.LoadScores(blobs["factor_scores.parquet"], f.c, m.Version)
		if err != nil {
			return err
		}
		f.scores = s
	case "prices":
		p, err := data.LoadPrices(blobs["prices.parquet"], blobs["coverage_report.json"], m.Version)
		if err != nil {
			return err
		}
		f.prices = p
	case "universe":
		u, err := data.LoadUniverse(blobs["sp500_current.parquet"], m.Version)
		if err != nil {
			return err
		}
		f.universe = u
	}
	f.log.Info("versión cargada", "dataset", m.Dataset, "version", m.Version, "s", time.Since(t0).Seconds())
	if f.scores != nil && f.prices != nil && f.universe != nil {
		f.onData(data.Build(f.c, f.scores, f.prices, f.universe, f.benchmark))
	}
	return nil
}

// Reconcile pregunta a cada servicio por su última versión y carga las que falten.
func (f *Feed) Reconcile(ctx context.Context) error {
	var errs []string
	for ds, base := range f.owners {
		b, status, err := f.get(ctx, base+"/datasets/"+ds+"/latest")
		if status == http.StatusNotFound {
			errs = append(errs, ds+": aún sin versiones")
			continue
		}
		if err != nil {
			errs = append(errs, err.Error())
			continue
		}
		var m manifest
		if err := json.Unmarshal(b, &m); err != nil {
			errs = append(errs, err.Error())
			continue
		}
		if err := f.Load(ctx, base+"/datasets/"+ds+"/versions/"+m.Version); err != nil {
			errs = append(errs, err.Error())
		}
	}
	if len(errs) > 0 {
		return fmt.Errorf("%s", strings.Join(errs, "; "))
	}
	return nil
}

// Run: carga inicial (reintentando hasta que los servicios respondan) y revisión periódica.
func (f *Feed) Run(ctx context.Context, every time.Duration) {
	wait := 2 * time.Second
	for {
		err := f.Reconcile(ctx)
		if err == nil {
			wait = every
		} else {
			f.log.Warn("no se pudieron cargar todos los datos; se reintentará", "error", err, "en", wait.String())
			wait = min(wait*2, every)
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(wait):
		}
	}
}

// Follow escucha Kafka desde el final (no le interesan eventos viejos: ya ha cargado lo último).
// Sin grupo de consumidores: cada réplica del gateway necesita TODOS los eventos.
func (f *Feed) Follow(ctx context.Context, brokers string) error {
	cl, err := kgo.NewClient(
		kgo.SeedBrokers(strings.Split(brokers, ",")...),
		kgo.ConsumeTopics("scores.published", "data.updated"),
		kgo.ConsumeResetOffset(kgo.NewOffset().AtEnd()),
	)
	if err != nil {
		return err
	}
	defer cl.Close()
	for {
		fetches := cl.PollFetches(ctx)
		if ctx.Err() != nil || fetches.IsClientClosed() {
			return nil
		}
		fetches.EachError(func(topic string, _ int32, err error) {
			f.log.Warn("error leyendo de Kafka", "topic", topic, "error", err)
		})
		fetches.EachRecord(func(r *kgo.Record) {
			ev, err := f.c.Validate(r.Value)
			if err != nil {
				f.log.Warn("evento que no cumple el contrato: se ignora", "topic", r.Topic, "offset", r.Offset, "error", err)
				return
			}
			url, _ := ev.Data["url"].(string)
			f.log.Info("evento", "type", ev.Type, "dataset", ev.Data["dataset"], "version", ev.Data["version"], "correlation_id", ev.CorrelationID)
			if err := f.Load(ctx, url); err != nil {
				f.log.Error("no se pudo cargar la versión anunciada (la revisión periódica lo reintentará)", "url", url, "error", err)
			}
		})
	}
}
