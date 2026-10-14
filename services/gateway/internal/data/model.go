package data

import (
	"crypto/sha1"
	"encoding/hex"
	"math"
	"sort"
	"strings"
	"time"
	"unicode"

	"github.com/heeriik/TrLavanda/services/gateway/internal/contracts"
)

// Data es todo lo que sirve la API, en memoria y de solo lectura. Cuando llega una versión
// nueva se construye otro Data y se cambia de golpe: las peticiones en curso siguen con el
// anterior y nunca ven una mezcla.
type Data struct {
	Version   string // identifica la combinación de versiones (para ETag y para la web)
	UpdatedAt string
	C         *contracts.Contracts
	Benchmark string

	Rows     []ScoreRow       // ordenadas por (fecha, rank)
	Dates    []int32          // fechas con ranking, ordenadas
	byDate   map[int32][]int  // fecha -> índices en Rows, por rank
	byTicker map[string][]int // ticker -> índices en Rows, por fecha
	Names    map[string]string
	Prices   map[string]*Series
	Coverage map[string]any
	Inputs   map[string]string // dataset -> versión
}

func Build(c *contracts.Contracts, s *Scores, p *Prices, u *Universe, benchmark string) *Data {
	d := &Data{
		C: c, Benchmark: benchmark, Prices: p.ByTicker, Coverage: p.Coverage,
		byDate: map[int32][]int{}, byTicker: map[string][]int{}, Names: map[string]string{},
		Inputs:    map[string]string{"scores": s.Version, "prices": p.Version, "universe": u.Version},
		UpdatedAt: time.Now().UTC().Format(time.RFC3339),
	}
	d.Rows = append([]ScoreRow(nil), s.Rows...)
	sort.SliceStable(d.Rows, func(i, j int) bool {
		a, b := d.Rows[i], d.Rows[j]
		return a.Date < b.Date || (a.Date == b.Date && a.Rank < b.Rank)
	})
	for i, r := range d.Rows {
		if len(d.byDate[r.Date]) == 0 {
			d.Dates = append(d.Dates, r.Date)
		}
		d.byDate[r.Date] = append(d.byDate[r.Date], i)
		d.byTicker[r.Ticker] = append(d.byTicker[r.Ticker], i)
		// Nombre: el de Wikipedia si existe; si no, el de EDGAR capitalizado (el más reciente).
		if wiki := u.Names[r.Ticker]; wiki != "" {
			d.Names[r.Ticker] = wiki
		} else {
			d.Names[r.Ticker] = PyTitle(r.Name)
		}
	}
	h := sha1.Sum([]byte(s.Version + "|" + p.Version + "|" + u.Version))
	d.Version = hex.EncodeToString(h[:6])
	return d
}

// LastDate: fecha del ranking más reciente.
func (d *Data) LastDate() int32 {
	if len(d.Dates) == 0 {
		return 0
	}
	return d.Dates[len(d.Dates)-1]
}

// Snapshot: filas del ranking en la última fecha <= on (on=nil: la más reciente), por rank.
func (d *Data) Snapshot(on *int32) []*ScoreRow {
	if len(d.Dates) == 0 {
		return nil
	}
	date := d.LastDate()
	if on != nil {
		i := sort.Search(len(d.Dates), func(i int) bool { return d.Dates[i] > *on })
		if i == 0 {
			return nil // no hay ningún ranking tan antiguo
		}
		date = d.Dates[i-1]
	}
	idx := d.byDate[date]
	out := make([]*ScoreRow, len(idx))
	for i, j := range idx {
		out[i] = &d.Rows[j]
	}
	return out
}

// History: todas las filas de un ticker, por fecha.
func (d *Data) History(ticker string) []*ScoreRow {
	idx := d.byTicker[ticker]
	out := make([]*ScoreRow, len(idx))
	for i, j := range idx {
		out[i] = &d.Rows[j]
	}
	return out
}

// PriceSeries: precios de un ticker desde `start` (incluido).
func (d *Data) PriceSeries(ticker string, start *int32) (dates []int32, adj []Num) {
	s := d.Prices[ticker]
	if s == nil {
		return nil, nil
	}
	i := 0
	if start != nil {
		i = sort.Search(len(s.Dates), func(i int) bool { return s.Dates[i] >= *start })
	}
	return s.Dates[i:], s.Adj[i:]
}

// LastRaw: último precio real del ticker.
func (d *Data) LastRaw(ticker string) (Num, bool) {
	s := d.Prices[ticker]
	if s == nil || len(s.Raw) == 0 {
		return Num{}, false
	}
	return s.Raw[len(s.Raw)-1], true
}

type Quote struct{ Px, D1, Y1 Num }

func div1(a, b Num) Num { // a/b - 1, con nulos
	if !a.OK || !b.OK {
		return Num{}
	}
	return Num{V: a.V/b.V - 1, OK: true}
}

// RankingQuote: precio y variación del día que se ven en la lista del ranking. Basta una fila
// (sin la anterior, la variación es nula).
func (d *Data) RankingQuote(ticker string) Quote {
	s := d.Prices[ticker]
	if s == nil || len(s.Dates) == 0 {
		return Quote{}
	}
	n := len(s.Adj)
	q := Quote{Px: s.Raw[n-1]}
	if n >= 2 {
		q.D1 = div1(s.Adj[n-1], s.Adj[n-2])
	}
	return q
}

// CompanyQuote: precio, variación del día y de 1 año (con dividendos). Necesita 2 filas.
func (d *Data) CompanyQuote(ticker string) Quote {
	s := d.Prices[ticker]
	if s == nil || len(s.Dates) < 2 {
		return Quote{}
	}
	n := len(s.Adj)
	q := Quote{Px: s.Raw[n-1], D1: div1(s.Adj[n-1], s.Adj[n-2])}
	yearAgo := s.Dates[n-1] - 365
	if i := sort.Search(n, func(i int) bool { return s.Dates[i] > yearAgo }); i > 0 {
		q.Y1 = div1(s.Adj[n-1], s.Adj[i-1])
	}
	return q
}

// Median como la de Polars: ignora los nulos, pero NO los NaN (los ordena al final).
func Median(vals []Num) Num {
	var xs []float64
	for _, v := range vals {
		if v.OK {
			xs = append(xs, v.V)
		}
	}
	if len(xs) == 0 {
		return Num{}
	}
	sort.Slice(xs, func(i, j int) bool {
		a, b := xs[i], xs[j]
		if math.IsNaN(b) {
			return !math.IsNaN(a)
		}
		return a < b
	})
	n := len(xs)
	if n%2 == 1 {
		return Num{V: xs[n/2], OK: true}
	}
	return Num{V: (xs[n/2-1] + xs[n/2]) / 2, OK: true}
}

// PyTitle imita str.title() de Python: mayúscula tras cualquier carácter que no sea letra
// ("MOODY'S CORP /DE/" -> "Moody'S Corp /De/", "3M CO" -> "3M Co").
func PyTitle(s string) string {
	var b strings.Builder
	prevCased := false
	for _, r := range s {
		switch {
		case unicode.IsUpper(r) || unicode.IsTitle(r):
			if prevCased {
				r = unicode.ToLower(r)
			}
			prevCased = true
		case unicode.IsLower(r):
			if !prevCased {
				r = unicode.ToTitle(r)
			}
			prevCased = true
		default:
			prevCased = false
		}
		b.WriteRune(r)
	}
	return b.String()
}

func (s *Series) sortByDate() {
	if sort.SliceIsSorted(s.Dates, func(i, j int) bool { return s.Dates[i] < s.Dates[j] }) {
		return
	}
	idx := make([]int, len(s.Dates))
	for i := range idx {
		idx[i] = i
	}
	sort.SliceStable(idx, func(i, j int) bool { return s.Dates[idx[i]] < s.Dates[idx[j]] })
	d, a, r := make([]int32, len(idx)), make([]Num, len(idx)), make([]Num, len(idx))
	for k, i := range idx {
		d[k], a[k], r[k] = s.Dates[i], s.Adj[i], s.Raw[i]
	}
	s.Dates, s.Adj, s.Raw = d, a, r
}

// Sectors: sectores presentes en unas filas, ordenados.
func Sectors(rows []*ScoreRow) []string {
	seen := map[string]bool{}
	var out []string
	for _, r := range rows {
		if !seen[r.Sector] {
			seen[r.Sector] = true
			out = append(out, r.Sector)
		}
	}
	sort.Strings(out)
	return out
}
