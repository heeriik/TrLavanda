package data

import (
	"os"

	"github.com/heeriik/TrLavanda/services/gateway/internal/contracts"
)

// Files: rutas locales de los cuatro archivos que necesita el gateway.
type Files struct {
	Scores, Prices, Current, Coverage string
}

// RepoFiles: los archivos de la carpeta data/ del repo (modo local, sin Kafka).
func RepoFiles(dataDir string) Files {
	return Files{
		Scores:   dataDir + "/processed/factor_scores.parquet",
		Prices:   dataDir + "/raw/prices/prices.parquet",
		Current:  dataDir + "/raw/universe/sp500_current.parquet",
		Coverage: dataDir + "/processed/coverage_report.json",
	}
}

// FromFiles construye un Data leyendo archivos locales (tests y modo local).
func FromFiles(c *contracts.Contracts, f Files, benchmark string) (*Data, error) {
	read := func(p string) ([]byte, error) { return os.ReadFile(p) }
	b, err := read(f.Scores)
	if err != nil {
		return nil, err
	}
	scores, err := LoadScores(b, c, "local")
	if err != nil {
		return nil, err
	}
	if b, err = read(f.Prices); err != nil {
		return nil, err
	}
	cov, _ := read(f.Coverage) // opcional
	prices, err := LoadPrices(b, cov, "local")
	if err != nil {
		return nil, err
	}
	universe := &Universe{Version: "local", Names: map[string]string{}}
	if b, err = read(f.Current); err == nil {
		if universe, err = LoadUniverse(b, "local"); err != nil {
			return nil, err
		}
	}
	return Build(c, scores, prices, universe, benchmark), nil
}
