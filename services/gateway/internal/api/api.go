// Package api sirve a la web los datos en memoria. Mismas rutas y respuestas que la API de
// referencia en Python (src/trlavanda/api, retirada); testdata/golden.json lo garantiza.
//
//	GET /api/meta                        versión de los datos y resumen
//	GET /api/ranking?date=&sector=&q=    ranking filtrado y paginado
//	GET /api/index/prices?start=         serie del S&P 500 (ETF SPY)
//	GET /api/companies/{ticker}          resumen de una empresa
//	GET /api/companies/{ticker}/prices   serie de precios (con dividendos)
//	GET /api/companies/{ticker}/factors  historia mensual de los factores
//	GET /api/companies/{ticker}/metrics  métricas frente a la mediana de su sector
//
// Caché HTTP: cada respuesta lleva un ETag que depende de la versión de los datos; si el
// navegador ya la tiene, se contesta 304 sin cuerpo.
package api

import (
	"crypto/sha1"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"slices"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/heeriik/TrLavanda/services/gateway/internal/data"
)

type Server struct {
	data    atomic.Pointer[data.Data] // se cambia entero cuando llega una versión nueva
	origins []string                  // CORS: orígenes permitidos (la web)
}

func New(origins []string) *Server { return &Server{origins: origins} }

// Swap publica un Data nuevo. Las peticiones en curso terminan con el anterior.
func (s *Server) Swap(d *data.Data) { s.data.Store(d) }

func (s *Server) Ready() bool { return s.data.Load() != nil }

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
	})
	s.route(mux, "GET /api/meta", s.meta)
	s.route(mux, "GET /api/ranking", s.ranking)
	s.route(mux, "GET /api/index/prices", s.indexPrices)
	s.route(mux, "GET /api/companies/{ticker}", s.company)
	s.route(mux, "GET /api/companies/{ticker}/prices", s.companyPrices)
	s.route(mux, "GET /api/companies/{ticker}/factors", s.companyFactors)
	s.route(mux, "GET /api/companies/{ticker}/metrics", s.companyMetrics)
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusNotFound, detail("Not Found"))
	})
	return s.cors(mux)
}

// httpError: error con código HTTP que acaba en {"detail": "..."} (como FastAPI).
type httpError struct {
	status int
	msg    string
}

func (e *httpError) Error() string { return e.msg }

func notFound(format string, a ...any) error {
	return &httpError{http.StatusNotFound, fmt.Sprintf(format, a...)}
}

func invalid(format string, a ...any) error {
	return &httpError{http.StatusUnprocessableEntity, fmt.Sprintf(format, a...)}
}

type handler func(d *data.Data, r *http.Request) (any, error)

// route envuelve un endpoint: datos cargados, ETag/304, errores y JSON.
func (s *Server) route(mux *http.ServeMux, pattern string, h handler) {
	mux.HandleFunc(pattern, func(w http.ResponseWriter, r *http.Request) {
		d := s.data.Load() // una sola lectura: toda la petición usa la misma versión
		if d == nil {
			writeJSON(w, http.StatusServiceUnavailable, detail("Los datos aún no se han cargado"))
			return
		}
		key := sha1.Sum([]byte(d.Version + ":" + r.URL.Path + "?" + r.URL.RawQuery))
		etag := `W/"` + hex.EncodeToString(key[:])[:16] + `"`
		if r.Header.Get("If-None-Match") == etag {
			w.Header().Set("ETag", etag)
			w.Header().Set("Cache-Control", "no-cache")
			w.WriteHeader(http.StatusNotModified)
			return
		}
		body, err := h(d, r)
		if err != nil {
			if he, ok := err.(*httpError); ok {
				writeJSON(w, he.status, detail(he.msg))
				return
			}
			writeJSON(w, http.StatusInternalServerError, detail(err.Error()))
			return
		}
		w.Header().Set("ETag", etag)
		w.Header().Set("Cache-Control", "no-cache")
		writeJSON(w, http.StatusOK, body)
	})
}

func (s *Server) cors(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if origin := r.Header.Get("Origin"); origin != "" && slices.Contains(s.origins, origin) {
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Access-Control-Expose-Headers", "ETag")
			w.Header().Add("Vary", "Origin")
			if r.Method == http.MethodOptions {
				w.Header().Set("Access-Control-Allow-Methods", "GET")
				w.Header().Set("Access-Control-Allow-Headers", "*")
				w.WriteHeader(http.StatusNoContent)
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}

func detail(msg string) map[string]string { return map[string]string{"detail": msg} }

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

// ---------- Números y fechas como los devuelve Python ----------

// num redondea como round(x, nd) de Python (redondeo exacto del binario, empates al par) y
// devuelve nil para nulos, NaN e infinitos.
func num(n data.Num, nd int) *float64 {
	if !n.Usable() {
		return nil
	}
	v, _ := strconv.ParseFloat(strconv.FormatFloat(n.V, 'f', nd, 64), 64)
	return &v
}

func iso(days int32) string {
	return time.Unix(int64(days)*86400, 0).UTC().Format(time.DateOnly)
}

func parseDate(r *http.Request, name string) (*int32, error) {
	v := r.URL.Query().Get(name)
	if v == "" {
		return nil, nil
	}
	t, err := time.Parse(time.DateOnly, v)
	if err != nil {
		return nil, invalid("%s: fecha no válida (formato AAAA-MM-DD)", name)
	}
	days := int32(t.Unix() / 86400)
	return &days, nil
}

func parseInt(r *http.Request, name string, def, min, max int) (int, error) {
	v := r.URL.Query().Get(name)
	if v == "" {
		return def, nil
	}
	n, err := strconv.Atoi(v)
	if err != nil || n < min || n > max {
		return 0, invalid("%s: debe ser un entero entre %d y %d", name, min, max)
	}
	return n, nil
}

// ---------- Endpoints ----------

type companyRow struct {
	T   string              `json:"t"`
	N   string              `json:"n"`
	S   string              `json:"s"`
	R   int64               `json:"r"`
	Sc  *float64            `json:"sc"`
	F   map[string]*float64 `json:"f"`
	Cap *float64            `json:"cap"`
	Px  *float64            `json:"px"`
	D1  *float64            `json:"d1"`
	Y1  *float64            `json:"y1"`
}

func makeRow(d *data.Data, r *data.ScoreRow, q data.Quote) companyRow {
	f := map[string]*float64{}
	for i, name := range d.C.Factors {
		f[name] = num(r.F[i], 2)
	}
	capB := data.Num{}
	if r.MarketCap.OK && r.MarketCap.V != 0 { // `if market_cap` en Python: 0 y nulo -> null
		capB = data.Num{V: r.MarketCap.V / 1e9, OK: true}
	}
	return companyRow{
		T: r.Ticker, N: d.Names[r.Ticker], S: r.Sector, R: r.Rank, Sc: num(r.Score, 2), F: f,
		Cap: num(capB, 1), Px: num(q.Px, 2), D1: num(q.D1, 4), Y1: num(q.Y1, 4),
	}
}

func (s *Server) meta(d *data.Data, r *http.Request) (any, error) {
	snap := d.Snapshot(nil)
	sinPrecios := 0
	if l, ok := d.Coverage["sin_precios"].([]any); ok {
		sinPrecios = len(l)
	}
	sectors := data.Sectors(snap)
	if sectors == nil {
		sectors = []string{}
	}
	return map[string]any{
		"version":    d.Version,
		"updated_at": d.UpdatedAt,
		"last_date":  iso(d.LastDate()),
		"n":          len(snap),
		"sectors":    sectors,
		"dates":      len(d.Dates),
		"coverage":   map[string]any{"tickers": d.Coverage["n_tickers"], "sin_precios": sinPrecios},
		"inputs":     d.Inputs,
	}, nil
}

func (s *Server) ranking(d *data.Data, r *http.Request) (any, error) {
	on, err := parseDate(r, "date")
	if err != nil {
		return nil, err
	}
	limit, err := parseInt(r, "limit", 30, 1, 600)
	if err != nil {
		return nil, err
	}
	offset, err := parseInt(r, "offset", 0, 0, 1<<31-1)
	if err != nil {
		return nil, err
	}
	snap := d.Snapshot(on)
	if sector := r.URL.Query().Get("sector"); sector != "" {
		snap = slices.DeleteFunc(slices.Clone(snap), func(x *data.ScoreRow) bool { return x.Sector != sector })
	}
	if q := r.URL.Query().Get("q"); q != "" {
		ql := strings.ToLower(strings.TrimSpace(q))
		snap = slices.DeleteFunc(slices.Clone(snap), func(x *data.ScoreRow) bool {
			return !strings.Contains(strings.ToLower(x.Ticker), ql) &&
				!strings.Contains(strings.ToLower(d.Names[x.Ticker]), ql)
		})
	}
	var date *string
	if len(snap) > 0 {
		v := iso(snap[0].Date)
		date = &v
	}
	rows := []companyRow{}
	for i := offset; i < len(snap) && i < offset+limit; i++ {
		rows = append(rows, makeRow(d, snap[i], d.RankingQuote(snap[i].Ticker)))
	}
	return map[string]any{"date": date, "total": len(snap), "rows": rows}, nil
}

func series(dates []int32, adj []data.Num) [][2]any {
	out := make([][2]any, len(dates))
	for i := range dates {
		out[i] = [2]any{iso(dates[i]), num(adj[i], 2)}
	}
	return out
}

func (s *Server) indexPrices(d *data.Data, r *http.Request) (any, error) {
	start, err := parseDate(r, "start")
	if err != nil {
		return nil, err
	}
	last, _ := d.LastRaw(d.Benchmark)
	return map[string]any{
		"ticker": d.Benchmark,
		"name":   "S&P 500",
		"last":   num(last, 2),
		"series": series(d.PriceSeries(d.Benchmark, start)),
	}, nil
}

// find: la empresa en el ranking más reciente (404 si no está).
func find(d *data.Data, r *http.Request) (*data.ScoreRow, []*data.ScoreRow, error) {
	ticker := r.PathValue("ticker")
	snap := d.Snapshot(nil)
	for _, row := range snap {
		if row.Ticker == strings.ToUpper(ticker) {
			return row, snap, nil
		}
	}
	return nil, nil, notFound("%s no está en el ranking actual", ticker)
}

func peers(snap []*data.ScoreRow, sector string) []*data.ScoreRow {
	return slices.DeleteFunc(slices.Clone(snap), func(x *data.ScoreRow) bool { return x.Sector != sector })
}

func (s *Server) company(d *data.Data, r *http.Request) (any, error) {
	row, snap, err := find(d, r)
	if err != nil {
		return nil, err
	}
	var sic *int64
	if row.Sic.Usable() {
		v := int64(row.Sic.V)
		sic = &v
	}
	return struct {
		companyRow
		Sic   *int64 `json:"sic"`
		Peers int    `json:"peers"`
		Total int    `json:"total"`
	}{makeRow(d, row, d.CompanyQuote(row.Ticker)), sic, len(peers(snap, row.Sector)), len(snap)}, nil
}

func (s *Server) companyPrices(d *data.Data, r *http.Request) (any, error) {
	row, _, err := find(d, r)
	if err != nil {
		return nil, err
	}
	start, err := parseDate(r, "start")
	if err != nil {
		return nil, err
	}
	var last *float64
	if v, ok := d.LastRaw(row.Ticker); ok {
		last = num(v, 2)
	}
	return map[string]any{"t": row.Ticker, "last": last, "series": series(d.PriceSeries(row.Ticker, start))}, nil
}

func (s *Server) companyFactors(d *data.Data, r *http.Request) (any, error) {
	row, _, err := find(d, r)
	if err != nil {
		return nil, err
	}
	keys := append(slices.Clone(d.C.Factors), "score")
	rows := [][]any{}
	for _, h := range d.History(row.Ticker) {
		line := []any{iso(h.Date)}
		for _, f := range h.F {
			line = append(line, num(f, 2))
		}
		rows = append(rows, append(line, num(h.Score, 2)))
	}
	return map[string]any{"t": row.Ticker, "keys": keys, "rows": rows}, nil
}

func (s *Server) companyMetrics(d *data.Data, r *http.Request) (any, error) {
	row, snap, err := find(d, r)
	if err != nil {
		return nil, err
	}
	group := peers(snap, row.Sector)
	metrics := []map[string]any{}
	for i, m := range d.C.Metrics {
		vals := make([]data.Num, len(group))
		for j, p := range group {
			vals[j] = p.M[i]
		}
		better := "high"
		if m.Sign < 0 {
			better = "low"
		}
		metrics = append(metrics, map[string]any{
			"k": m.Key, "f": m.Factor, "label": m.Label,
			"v": num(row.M[i], 4), "med": num(data.Median(vals), 4), "z": num(row.Z[i], 2),
			"better": better,
		})
	}
	return map[string]any{"t": row.Ticker, "sector": row.Sector, "peers": len(group), "metrics": metrics}, nil
}
