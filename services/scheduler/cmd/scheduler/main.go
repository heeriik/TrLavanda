// Scheduler de TrLavanda: publica `cmd.ingest` cada día a la hora configurada.
//
//	SCHEDULE_AT=22:30  SCHEDULE_DAYS=mon,tue,wed,thu,fri  (UTC; Wall Street cierra a las 20:00/21:00 UTC)
//	DATASETS=universe,edgar,prices  KAFKA_BOOTSTRAP=kafka:29092
//
// Al arrancar publica también la última franja que ya debió ejecutarse (por si estaba apagado).
// No guarda estado: el run_id es determinista (daily-AAAA-MM-DD) e ingest ignora los repetidos.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/heeriik/TrLavanda/libs/go/contracts"
	"github.com/heeriik/TrLavanda/libs/go/events"
	"github.com/heeriik/TrLavanda/services/scheduler/internal/schedule"
)

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

type state struct {
	mu      sync.Mutex
	next    time.Time
	lastRun string
	lastAt  time.Time
	lastErr string
}

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	fail := func(msg string, err error) {
		log.Error(msg, "error", err)
		os.Exit(1)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	sched, err := schedule.Parse(env("SCHEDULE_AT", "22:30"), env("SCHEDULE_DAYS", "mon,tue,wed,thu,fri"))
	if err != nil {
		fail("horario", err)
	}
	datasets := strings.Split(env("DATASETS", "universe,edgar,prices"), ",")
	dir, err := contracts.FindDir()
	if err != nil {
		fail("contratos", err)
	}
	c, err := contracts.Load(dir)
	if err != nil {
		fail("contratos", err)
	}
	pub, err := events.NewPublisher(c, env("KAFKA_BOOTSTRAP", "kafka:29092"), "scheduler")
	if err != nil {
		fail("kafka", err)
	}
	defer pub.Close()

	st := &state{}
	publish := func(slot time.Time) {
		runID := schedule.RunID(slot)
		for wait := 5 * time.Second; ; wait = min(wait*2, 5*time.Minute) { // reintenta si Kafka no está
			sendCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
			_, err := pub.Publish(sendCtx, "cmd.ingest", map[string]any{"run_id": runID, "datasets": datasets}, runID)
			cancel()
			st.mu.Lock()
			st.lastRun, st.lastAt, st.lastErr = runID, time.Now().UTC(), ""
			if err != nil {
				st.lastErr = err.Error()
			}
			st.mu.Unlock()
			if err == nil {
				log.Info("cmd.ingest publicado", "run_id", runID, "datasets", datasets, "correlation_id", runID)
				return
			}
			log.Warn("no se pudo publicar; se reintentará", "run_id", runID, "error", err, "en", wait.String())
			select {
			case <-ctx.Done():
				return
			case <-time.After(wait):
			}
		}
	}

	go func() {
		publish(sched.LastDue(time.Now())) // recuperar la última franja (ingest ignora si ya se hizo)
		for {
			next := sched.Next(time.Now())
			st.mu.Lock()
			st.next = next
			st.mu.Unlock()
			log.Info("próxima ejecución", "at", next.Format(time.RFC3339), "run_id", schedule.RunID(next))
			select {
			case <-ctx.Done():
				return
			case <-time.After(time.Until(next)):
				publish(next)
			}
		}
	}()

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		st.mu.Lock()
		defer st.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"ok": true, "next": st.next.Format(time.RFC3339), "next_run_id": schedule.RunID(st.next),
			"last_run_id": st.lastRun, "last_at": st.lastAt.Format(time.RFC3339), "last_error": st.lastErr,
		})
	})
	server := &http.Server{Addr: env("SCHEDULER_ADDR", "127.0.0.1:8003"), Handler: mux, ReadHeaderTimeout: 10 * time.Second}
	go func() {
		<-ctx.Done()
		_ = server.Shutdown(context.Background())
	}()
	log.Info("scheduler en marcha", "addr", server.Addr, "at", env("SCHEDULE_AT", "22:30")+" UTC")
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		fail("servidor", err)
	}
}
