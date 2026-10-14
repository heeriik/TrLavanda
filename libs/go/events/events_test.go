package events

import (
	"encoding/json"
	"regexp"
	"testing"
	"time"

	"github.com/heeriik/TrLavanda/libs/go/contracts"
)

func load(t *testing.T) *contracts.Contracts {
	dir, err := contracts.FindDir()
	if err != nil {
		t.Fatal(err)
	}
	c, err := contracts.Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func TestBuildValidaYUsaLaClave(t *testing.T) {
	c := load(t)
	now := time.Date(2026, 10, 14, 22, 30, 0, 0, time.UTC)
	value, key, err := Build(c, "cmd.ingest", "scheduler", "",
		map[string]any{"run_id": "daily-2026-10-14", "datasets": []string{"universe", "prices"}}, now)
	if err != nil {
		t.Fatal(err)
	}
	if key != "daily-2026-10-14" {
		t.Errorf("clave %q", key)
	}
	var ev map[string]any
	_ = json.Unmarshal(value, &ev)
	if ev["type"] != "cmd.ingest" || ev["occurred_at"] != "2026-10-14T22:30:00Z" || ev["correlation_id"] != ev["id"] {
		t.Errorf("evento: %v", ev)
	}

	// Un comando que no cumple el contrato no llega a construirse.
	if _, _, err := Build(c, "cmd.ingest", "scheduler", "", map[string]any{"run_id": "x", "datasets": []string{"acciones"}}, now); err == nil {
		t.Error("dataset desconocido: debería fallar")
	}
	if _, _, err := Build(c, "no.existe", "scheduler", "", map[string]any{}, now); err == nil {
		t.Error("topic desconocido: debería fallar")
	}
}

func TestUUID(t *testing.T) {
	re := regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)
	if a, b := UUID(), UUID(); !re.MatchString(a) || a == b {
		t.Errorf("uuid %q %q", a, b)
	}
}
