// Package contracts carga los contratos compartidos con Python (carpeta contracts/ del repo):
// la definición de los factores y los JSON Schema de los eventos de Kafka.
package contracts

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// Metric es una métrica del ranking: a qué factor pertenece, su signo y su etiqueta.
type Metric struct {
	Key    string
	Factor string
	Sign   int // +1: más alto es mejor; -1: más bajo es mejor
	Label  string
}

// Topic: configuración de un topic de Kafka (contracts/topics.json).
type Topic struct {
	Event string `json:"event"` // tipo de evento (= esquema) que llevan sus mensajes
	Key   string `json:"key"`   // campo de `data` que se usa como clave (o ese texto si no existe)
}

type Contracts struct {
	Dir     string
	Factors []string // en el orden del contrato (value, quality, momentum, growth)
	Metrics []Metric // todas, en orden
	Topics  map[string]Topic
	schemas map[string]*jsonschema.Schema
}

// FindDir devuelve la carpeta de contratos: $TRL_CONTRACTS_DIR o la primera "contracts" que
// aparezca subiendo desde el directorio actual (así funciona en los tests y en local).
func FindDir() (string, error) {
	if d := os.Getenv("TRL_CONTRACTS_DIR"); d != "" {
		return d, nil
	}
	dir, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		candidate := filepath.Join(dir, "contracts")
		if _, err := os.Stat(filepath.Join(candidate, "topics.json")); err == nil {
			return candidate, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", errors.New("no se encuentra la carpeta contracts/ (defina TRL_CONTRACTS_DIR)")
		}
		dir = parent
	}
}

func Load(dir string) (*Contracts, error) {
	c := &Contracts{Dir: dir, schemas: map[string]*jsonschema.Schema{}}
	if err := c.loadFactors(); err != nil {
		return nil, fmt.Errorf("factors.json: %w", err)
	}
	if err := c.loadTopics(); err != nil {
		return nil, fmt.Errorf("topics.json: %w", err)
	}
	if err := c.loadSchemas(); err != nil {
		return nil, fmt.Errorf("esquemas de eventos: %w", err)
	}
	return c, nil
}

func (c *Contracts) loadFactors() error {
	raw, err := os.ReadFile(filepath.Join(c.Dir, "factors.json"))
	if err != nil {
		return err
	}
	var doc struct {
		Factors json.RawMessage   `json:"factors"`
		Labels  map[string]string `json:"labels"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		return err
	}
	// "factors" es un objeto cuyo ORDEN importa; un map de Go lo perdería: se lee token a token.
	dec := json.NewDecoder(bytes.NewReader(doc.Factors))
	if _, err := dec.Token(); err != nil { // {
		return err
	}
	for dec.More() {
		tok, err := dec.Token()
		if err != nil {
			return err
		}
		factor := tok.(string)
		var metrics [][2]any
		if err := dec.Decode(&metrics); err != nil {
			return err
		}
		c.Factors = append(c.Factors, factor)
		for _, m := range metrics {
			key, _ := m[0].(string)
			sign, _ := m[1].(float64)
			label, ok := doc.Labels[key]
			if !ok {
				return fmt.Errorf("falta la etiqueta de %q", key)
			}
			c.Metrics = append(c.Metrics, Metric{Key: key, Factor: factor, Sign: int(sign), Label: label})
		}
	}
	return nil
}

func (c *Contracts) loadTopics() error {
	raw, err := os.ReadFile(filepath.Join(c.Dir, "topics.json"))
	if err != nil {
		return err
	}
	var doc struct {
		Topics map[string]Topic `json:"topics"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		return err
	}
	c.Topics = doc.Topics
	return nil
}

func (c *Contracts) loadSchemas() error {
	comp := jsonschema.NewCompiler()
	comp.AssertFormat() // uuid, date, date-time, uri... se comprueban, no solo se anotan
	files, err := filepath.Glob(filepath.Join(c.Dir, "events", "*.schema.json"))
	if err != nil {
		return err
	}
	ids := map[string]string{}
	for _, f := range files {
		raw, err := os.Open(f)
		if err != nil {
			return err
		}
		doc, err := jsonschema.UnmarshalJSON(raw)
		raw.Close()
		if err != nil {
			return fmt.Errorf("%s: %w", f, err)
		}
		id, _ := doc.(map[string]any)["$id"].(string)
		if err := comp.AddResource(id, doc); err != nil {
			return err
		}
		name := filepath.Base(f)
		ids[name[:len(name)-len(".schema.json")]] = id
	}
	for name, id := range ids {
		s, err := comp.Compile(id)
		if err != nil {
			return fmt.Errorf("%s: %w", name, err)
		}
		c.schemas[name] = s
	}
	if c.schemas["envelope"] == nil {
		return errors.New("falta envelope.schema.json")
	}
	return nil
}

// Event es un evento de Kafka ya validado.
type Event struct {
	ID            string         `json:"id"`
	Type          string         `json:"type"`
	CorrelationID string         `json:"correlation_id"`
	Source        string         `json:"source"`
	Data          map[string]any `json:"data"`
}

// Validate comprueba el sobre y su `data` contra los esquemas (lo mismo que trlavanda.bus.validate).
func (c *Contracts) Validate(raw []byte) (*Event, error) {
	inst, err := jsonschema.UnmarshalJSON(bytes.NewReader(raw))
	if err != nil {
		return nil, fmt.Errorf("no es JSON: %w", err)
	}
	if err := c.schemas["envelope"].Validate(inst); err != nil {
		return nil, err
	}
	typ := inst.(map[string]any)["type"].(string)
	s, ok := c.schemas[typ]
	if !ok {
		return nil, fmt.Errorf("tipo sin esquema: %s", typ)
	}
	if err := s.Validate(inst.(map[string]any)["data"]); err != nil {
		return nil, err
	}
	var ev Event
	if err := json.Unmarshal(raw, &ev); err != nil {
		return nil, err
	}
	return &ev, nil
}
