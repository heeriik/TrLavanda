// Gateway de TrLavanda: la API que usa la web.
//
// Modo normal (Docker): carga los datos de ingest y factors y se mantiene al día con Kafka.
//
//	KAFKA_BOOTSTRAP=kafka:29092 INGEST_URL=http://ingest:8000 FACTORS_URL=http://factors:8000 gateway
//
// Modo local (sin Kafka ni servicios): lee la carpeta data/ del repo.
//
//	go run ./cmd/gateway -local ../../data
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/heeriik/TrLavanda/libs/go/contracts"
	"github.com/heeriik/TrLavanda/services/gateway/internal/api"
	"github.com/heeriik/TrLavanda/services/gateway/internal/data"
	"github.com/heeriik/TrLavanda/services/gateway/internal/feed"
)

const benchmark = "SPY"

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func main() {
	addr := flag.String("addr", env("GATEWAY_ADDR", "127.0.0.1:8000"), "dirección de escucha")
	local := flag.String("local", "", "modo local: carpeta data/ del repo (sin Kafka)")
	flag.Parse()

	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	dir, err := contracts.FindDir()
	if err != nil {
		log.Error("contratos", "error", err)
		os.Exit(1)
	}
	c, err := contracts.Load(dir)
	if err != nil {
		log.Error("contratos", "error", err)
		os.Exit(1)
	}

	origins := strings.Split(env("CORS_ORIGINS",
		"http://localhost:8600,http://127.0.0.1:8600,https://heeriik.github.io"), ",")
	srv := api.New(origins)
	versions := func() map[string]string { return map[string]string{} }

	if *local != "" {
		d, err := data.FromFiles(c, data.RepoFiles(*local), benchmark)
		if err != nil {
			log.Error("modo local", "error", err)
			os.Exit(1)
		}
		srv.Swap(d)
		log.Info("modo local", "dir", *local, "filas", len(d.Rows))
	} else {
		f := feed.New(c, env("INGEST_URL", "http://ingest:8000"), env("FACTORS_URL", "http://factors:8000"),
			benchmark, srv.Swap, log)
		versions = f.Versions
		go func() {
			if err := f.Follow(ctx, env("KAFKA_BOOTSTRAP", "kafka:29092")); err != nil {
				log.Error("kafka", "error", err)
			}
		}()
		go f.Run(ctx, 5*time.Minute)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "ready": srv.Ready(), "versions": versions()})
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if !srv.Ready() {
			w.WriteHeader(http.StatusServiceUnavailable)
		}
		_ = json.NewEncoder(w).Encode(map[string]bool{"ready": srv.Ready()})
	})
	mux.Handle("/", srv.Handler())
	server := &http.Server{Addr: *addr, Handler: mux, ReadHeaderTimeout: 10 * time.Second}

	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	log.Info("gateway escuchando", "addr", *addr)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Error("servidor", "error", err)
		os.Exit(1)
	}
}
