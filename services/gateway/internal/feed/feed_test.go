package feed

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/heeriik/TrLavanda/services/gateway/internal/contracts"
	"github.com/heeriik/TrLavanda/services/gateway/internal/data"
)

const fixture = "../../testdata/fixture/"

// fakeService sirve versiones como ingest/factors a partir de la fixture.
func fakeService(t *testing.T, version string, corrupt bool) *httptest.Server {
	files := map[string]map[string]string{ // dataset -> archivo publicado -> archivo en la fixture
		"scores":   {"factor_scores.parquet": "factor_scores.parquet"},
		"prices":   {"prices.parquet": "prices.parquet", "coverage_report.json": "coverage_report.json"},
		"universe": {"sp500_current.parquet": "sp500_current.parquet"},
	}
	mux := http.NewServeMux()
	for ds, fs := range files {
		manifest := map[string]any{"dataset": ds, "version": version, "files": map[string]any{}}
		for name, src := range fs {
			b, err := os.ReadFile(fixture + src)
			if err != nil {
				t.Fatal(err)
			}
			sum := sha256.Sum256(b)
			manifest["files"].(map[string]any)[name] = map[string]string{"sha256": hex.EncodeToString(sum[:])}
			if corrupt && ds == "prices" {
				b = append([]byte{}, b...)
				b[len(b)/2] ^= 0xff
			}
			mux.HandleFunc("GET /datasets/"+ds+"/versions/"+version+"/files/"+name, func(w http.ResponseWriter, r *http.Request) {
				w.Write(b)
			})
		}
		m, _ := json.Marshal(manifest)
		for _, p := range []string{"/datasets/" + ds + "/latest", "/datasets/" + ds + "/versions/" + version} {
			mux.HandleFunc("GET "+p, func(w http.ResponseWriter, r *http.Request) { w.Write(m) })
		}
	}
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv
}

func newFeed(t *testing.T, url string, got *[]*data.Data) *Feed {
	dir, err := contracts.FindDir()
	if err != nil {
		t.Fatal(err)
	}
	c, err := contracts.Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	return New(c, url, url, "SPY", func(d *data.Data) { *got = append(*got, d) }, log)
}

func TestCargaInicialYVersionesViejas(t *testing.T) {
	srv := fakeService(t, "20261014T090000Z", false)
	var got []*data.Data
	f := newFeed(t, srv.URL, &got)
	if err := f.Reconcile(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].LastDate() == 0 {
		t.Fatalf("se esperaba un Data construido, hay %d", len(got))
	}
	// La misma versión otra vez (evento repetido o revisión periódica): no se recarga.
	if err := f.Load(context.Background(), srv.URL+"/datasets/scores/versions/20261014T090000Z"); err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 {
		t.Fatalf("una versión repetida no debe reconstruir los datos (%d)", len(got))
	}
}

func TestDescargaCorruptaSeRechaza(t *testing.T) {
	srv := fakeService(t, "20261014T090000Z", true)
	var got []*data.Data
	f := newFeed(t, srv.URL, &got)
	err := f.Reconcile(context.Background())
	if err == nil || !strings.Contains(err.Error(), "sha256") {
		t.Fatalf("se esperaba error de sha256, llega %v", err)
	}
	if len(got) != 0 || f.Versions()["prices"] != "" {
		t.Fatal("con un archivo corrupto no se deben publicar datos")
	}
}
