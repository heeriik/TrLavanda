package data

import (
	"encoding/json"
	"fmt"

	"github.com/heeriik/TrLavanda/services/gateway/internal/contracts"
)

// ScoreRow es una fila del ranking: una empresa en una fecha.
type ScoreRow struct {
	Date      int32
	Ticker    string
	Name      string // nombre en EDGAR (mayúsculas)
	Sector    string
	Sic       Num
	MarketCap Num
	Score     Num
	Rank      int64
	F         []Num // un valor por factor (orden del contrato)
	M         []Num // valor de cada métrica
	Z         []Num // z-score de cada métrica
}

// Scores: dataset "scores" de factors (solo filas con score no nulo).
type Scores struct {
	Version string
	Rows    []ScoreRow
}

// Series: precios de un ticker ordenados por fecha.
type Series struct {
	Dates []int32
	Adj   []Num // rentabilidad total (con dividendos)
	Raw   []Num // precio que se veía ese día
}

// Prices: dataset "prices" de ingest.
type Prices struct {
	Version  string
	ByTicker map[string]*Series
	Coverage map[string]any
}

// Universe: dataset "universe" de ingest (solo hace falta el nombre de los miembros actuales).
type Universe struct {
	Version string
	Names   map[string]string
}

func LoadScores(b []byte, c *contracts.Contracts, version string) (*Scores, error) {
	cols := []string{"date", "ticker", "name", "sector", "sic", "market_cap", "score", "rank"}
	for _, f := range c.Factors {
		cols = append(cols, "f_"+f)
	}
	for _, m := range c.Metrics {
		cols = append(cols, m.Key, "z_"+m.Key)
	}
	t, err := readParquet(b, cols)
	if err != nil {
		return nil, fmt.Errorf("scores: %w", err)
	}
	defer t.release()

	dates, err := t.dates("date")
	if err != nil {
		return nil, err
	}
	tickers, _, err := t.strings("ticker")
	if err != nil {
		return nil, err
	}
	names, namesOK, err := t.strings("name")
	if err != nil {
		return nil, err
	}
	sectors, _, err := t.strings("sector")
	if err != nil {
		return nil, err
	}
	nums := map[string][]Num{}
	for _, col := range cols[4:] {
		if nums[col], err = t.nums(col); err != nil {
			return nil, err
		}
	}

	s := &Scores{Version: version}
	for i := range t.n {
		if !nums["score"][i].OK { // como `filter(score.is_not_null())`: los NaN se quedan
			continue
		}
		name := names[i]
		if !namesOK[i] {
			name = "None" // str(None) en Python
		}
		r := ScoreRow{
			Date: dates[i], Ticker: tickers[i], Name: name, Sector: sectors[i],
			Sic: nums["sic"][i], MarketCap: nums["market_cap"][i], Score: nums["score"][i],
			Rank: int64(nums["rank"][i].V),
		}
		for _, f := range c.Factors {
			r.F = append(r.F, nums["f_"+f][i])
		}
		for _, m := range c.Metrics {
			r.M = append(r.M, nums[m.Key][i])
			r.Z = append(r.Z, nums["z_"+m.Key][i])
		}
		s.Rows = append(s.Rows, r)
	}
	return s, nil
}

func LoadPrices(parquet, coverage []byte, version string) (*Prices, error) {
	t, err := readParquet(parquet, []string{"date", "ticker", "adj_close", "raw_close"})
	if err != nil {
		return nil, fmt.Errorf("prices: %w", err)
	}
	defer t.release()
	dates, err := t.dates("date")
	if err != nil {
		return nil, err
	}
	tickers, _, err := t.strings("ticker")
	if err != nil {
		return nil, err
	}
	adj, err := t.nums("adj_close")
	if err != nil {
		return nil, err
	}
	raw, err := t.nums("raw_close")
	if err != nil {
		return nil, err
	}
	p := &Prices{Version: version, ByTicker: map[string]*Series{}, Coverage: map[string]any{}}
	for i := range t.n {
		s := p.ByTicker[tickers[i]]
		if s == nil {
			s = &Series{}
			p.ByTicker[tickers[i]] = s
		}
		s.Dates = append(s.Dates, dates[i])
		s.Adj = append(s.Adj, adj[i])
		s.Raw = append(s.Raw, raw[i])
	}
	for _, s := range p.ByTicker {
		s.sortByDate()
	}
	if len(coverage) > 0 {
		if err := json.Unmarshal(coverage, &p.Coverage); err != nil {
			return nil, fmt.Errorf("coverage_report.json: %w", err)
		}
	}
	return p, nil
}

func LoadUniverse(b []byte, version string) (*Universe, error) {
	t, err := readParquet(b, []string{"ticker", "name"})
	if err != nil {
		return nil, fmt.Errorf("universe: %w", err)
	}
	defer t.release()
	tickers, _, err := t.strings("ticker")
	if err != nil {
		return nil, err
	}
	names, _, err := t.strings("name")
	if err != nil {
		return nil, err
	}
	u := &Universe{Version: version, Names: map[string]string{}}
	for i := range t.n {
		u.Names[tickers[i]] = names[i]
	}
	return u, nil
}
