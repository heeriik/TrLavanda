package contracts

import (
	"strings"
	"testing"
)

func load(t *testing.T) *Contracts {
	t.Helper()
	dir, err := FindDir()
	if err != nil {
		t.Fatal(err)
	}
	c, err := Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func TestFactoresEnOrden(t *testing.T) {
	c := load(t)
	if got := strings.Join(c.Factors, ","); got != "value,quality,momentum,growth" {
		t.Fatalf("factores: %s", got)
	}
	if len(c.Metrics) != 10 || c.Metrics[6].Key != "debt_assets" || c.Metrics[6].Sign != -1 {
		t.Fatalf("métricas: %+v", c.Metrics)
	}
}

const valido = `{"id": "6f1c1a52-6a9e-4c55-9d0a-0d1f3c1c2b11", "type": "scores.published",
 "schema_version": 1, "occurred_at": "2026-10-14T09:33:16Z", "source": "factors",
 "correlation_id": "run-1", "data": {"version": "20261014T093316Z", "as_of": "2026-10-13",
 "rows": 491, "url": "http://factors:8000/datasets/scores/versions/20261014T093316Z",
 "inputs": {"prices": "20261014T090922Z"}}}`

func TestValidacion(t *testing.T) {
	c := load(t)
	ev, err := c.Validate([]byte(valido))
	if err != nil {
		t.Fatal(err)
	}
	if ev.Type != "scores.published" || ev.Data["rows"].(float64) != 491 {
		t.Fatalf("evento: %+v", ev)
	}
	for name, raw := range map[string]string{
		"no es JSON":       `{roto`,
		"falta data":       strings.Replace(valido, `"data"`, `"datos"`, 1),
		"tipo desconocido": strings.Replace(valido, `"scores.published"`, `"otro"`, 1),
		"version mal":      strings.Replace(valido, `"version": "20261014T093316Z"`, `"version": "v1"`, 1),
		"uuid mal":         strings.Replace(valido, `6f1c1a52-6a9e`, `xxxx`, 1),
		"campo de más":     strings.Replace(valido, `"rows": 491`, `"rows": 491, "extra": 1`, 1),
	} {
		if _, err := c.Validate([]byte(raw)); err == nil {
			t.Errorf("%s: debería fallar", name)
		}
	}
}
