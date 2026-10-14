package api

import (
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"sort"
	"testing"

	"github.com/heeriik/TrLavanda/libs/go/contracts"
	"github.com/heeriik/TrLavanda/services/gateway/internal/data"
)

const fixture = "../../testdata/fixture/"

func newServer(t *testing.T) *httptest.Server {
	t.Helper()
	dir, err := contracts.FindDir()
	if err != nil {
		t.Fatal(err)
	}
	c, err := contracts.Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	d, err := data.FromFiles(c, data.Files{
		Scores:   fixture + "factor_scores.parquet",
		Prices:   fixture + "prices.parquet",
		Current:  fixture + "sp500_current.parquet",
		Coverage: fixture + "coverage_report.json",
	}, "SPY")
	if err != nil {
		t.Fatal(err)
	}
	s := New([]string{"http://localhost:8600"})
	s.Swap(d)
	srv := httptest.NewServer(s.Handler())
	t.Cleanup(srv.Close)
	return srv
}

type golden struct {
	URL    string `json:"url"`
	Status int    `json:"status"`
	Body   any    `json:"body"`
}

// TestParidadConPython: cada respuesta debe ser igual a la que daba la API de referencia en Python.
func TestParidadConPython(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/golden.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []golden
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	srv := newServer(t)
	for _, c := range cases {
		t.Run(c.URL, func(t *testing.T) {
			res, err := http.Get(srv.URL + c.URL)
			if err != nil {
				t.Fatal(err)
			}
			defer res.Body.Close()
			if res.StatusCode != c.Status {
				t.Fatalf("código %d, se esperaba %d", res.StatusCode, c.Status)
			}
			if c.Body == nil { // errores de validación: solo cuenta el código
				return
			}
			var got any
			b, _ := io.ReadAll(res.Body)
			if err := json.Unmarshal(b, &got); err != nil {
				t.Fatal(err)
			}
			if c.URL == "/api/meta" { // cambian en cada carga; "inputs" es un campo nuevo
				for _, k := range []string{"version", "updated_at", "inputs"} {
					delete(got.(map[string]any), k)
				}
			}
			if diffs := diff("", c.Body, got); len(diffs) > 0 {
				t.Errorf("%d diferencias:\n%v", len(diffs), diffs)
			}
		})
	}
}

// diff devuelve las rutas JSON donde `want` y `got` no coinciden.
func diff(path string, want, got any) []string {
	switch w := want.(type) {
	case map[string]any:
		g, ok := got.(map[string]any)
		if !ok {
			return []string{fmt.Sprintf("%s: se esperaba objeto, llega %v", path, got)}
		}
		var out []string
		keys := map[string]bool{}
		for k := range w {
			keys[k] = true
		}
		for k := range g {
			keys[k] = true
		}
		sorted := make([]string, 0, len(keys))
		for k := range keys {
			sorted = append(sorted, k)
		}
		sort.Strings(sorted)
		for _, k := range sorted {
			out = append(out, diff(path+"."+k, w[k], g[k])...)
		}
		return out
	case []any:
		g, ok := got.([]any)
		if !ok || len(g) != len(w) {
			return []string{fmt.Sprintf("%s: se esperaba lista de %d, llega %v", path, len(w), got)}
		}
		var out []string
		for i := range w {
			out = append(out, diff(fmt.Sprintf("%s[%d]", path, i), w[i], g[i])...)
		}
		return out
	case float64:
		if g, ok := got.(float64); ok && (g == w || math.Abs(g-w) < 1e-12) {
			return nil
		}
	default:
		if reflect.DeepEqual(want, got) {
			return nil
		}
	}
	return []string{fmt.Sprintf("%s: se esperaba %v, llega %v", path, want, got)}
}

func TestETag304(t *testing.T) {
	srv := newServer(t)
	res, err := http.Get(srv.URL + "/api/ranking")
	if err != nil {
		t.Fatal(err)
	}
	res.Body.Close()
	etag := res.Header.Get("ETag")
	req, _ := http.NewRequest("GET", srv.URL+"/api/ranking", nil)
	req.Header.Set("If-None-Match", etag)
	res, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	res.Body.Close()
	if etag == "" || res.StatusCode != http.StatusNotModified {
		t.Fatalf("etag %q, código %d", etag, res.StatusCode)
	}
}

func TestCORS(t *testing.T) {
	srv := newServer(t)
	for origin, want := range map[string]string{"http://localhost:8600": "http://localhost:8600", "https://evil.example": ""} {
		req, _ := http.NewRequest("GET", srv.URL+"/api/meta", nil)
		req.Header.Set("Origin", origin)
		res, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		res.Body.Close()
		if got := res.Header.Get("Access-Control-Allow-Origin"); got != want {
			t.Errorf("%s: Allow-Origin %q, se esperaba %q", origin, got, want)
		}
	}
}

func TestSinDatos503(t *testing.T) {
	srv := httptest.NewServer(New(nil).Handler())
	defer srv.Close()
	res, err := http.Get(srv.URL + "/api/meta")
	if err != nil {
		t.Fatal(err)
	}
	res.Body.Close()
	if res.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("código %d", res.StatusCode)
	}
}

func TestRedondeoComoPython(t *testing.T) {
	for _, c := range []struct {
		x    float64
		nd   int
		want float64
	}{
		{0.3125, 2, 0.31}, // empate exacto: al par
		{0.3175, 2, 0.32},
		{2.675, 2, 2.67}, // 2.675 es en binario 2.67499999...
		{-0.00005, 4, -0.0001},
		{12.34, 1, 12.3},
	} {
		if got := *num(data.Num{V: c.x, OK: true}, c.nd); got != c.want {
			t.Errorf("round(%v, %d) = %v, se esperaba %v", c.x, c.nd, got, c.want)
		}
	}
	if num(data.Num{V: math.NaN(), OK: true}, 2) != nil || num(data.Num{}, 2) != nil {
		t.Error("NaN y nulo deben dar null")
	}
}
