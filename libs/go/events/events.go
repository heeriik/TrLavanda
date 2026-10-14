// Package events construye y publica eventos con el mismo sobre que trlavanda.bus (Python):
// id, type, schema_version, occurred_at, source, correlation_id y data. Todo evento se valida
// contra contracts/ ANTES de enviarlo: un productor nunca pone en Kafka algo que rompa el contrato.
package events

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/twmb/franz-go/pkg/kgo"

	"github.com/heeriik/TrLavanda/libs/go/contracts"
)

const SchemaVersion = 1

// UUID v4 aleatorio (para `id`).
func UUID() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	b[6] = b[6]&0x0f | 0x40 // versión 4
	b[8] = b[8]&0x3f | 0x80 // variante RFC 4122
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}

// Build devuelve el evento (JSON) para `topic` ya validado, y la clave del mensaje.
func Build(c *contracts.Contracts, topic, source, correlationID string, data map[string]any, now time.Time) (value []byte, key string, err error) {
	t, ok := c.Topics[topic]
	if !ok {
		return nil, "", fmt.Errorf("topic desconocido: %s", topic)
	}
	id := UUID()
	if correlationID == "" {
		correlationID = id // sin cadena previa, la cadena empieza aquí
	}
	value, err = json.Marshal(map[string]any{
		"id":             id,
		"type":           t.Event,
		"schema_version": SchemaVersion,
		"occurred_at":    now.UTC().Format("2006-01-02T15:04:05Z"),
		"source":         source,
		"correlation_id": correlationID,
		"data":           data,
	})
	if err != nil {
		return nil, "", err
	}
	if _, err := c.Validate(value); err != nil {
		return nil, "", fmt.Errorf("no cumple el contrato: %w", err)
	}
	key = t.Key // como en Python: el campo de `data` indicado, o ese texto si no existe
	if v, ok := data[t.Key]; ok {
		key = fmt.Sprint(v)
	}
	return value, key, nil
}

// Publisher publica eventos validados en Kafka (acks de todas las réplicas + idempotencia).
type Publisher struct {
	c      *contracts.Contracts
	source string
	cl     *kgo.Client
}

func NewPublisher(c *contracts.Contracts, brokers, source string) (*Publisher, error) {
	cl, err := kgo.NewClient(kgo.SeedBrokers(strings.Split(brokers, ",")...))
	if err != nil {
		return nil, err
	}
	return &Publisher{c: c, source: source, cl: cl}, nil
}

func (p *Publisher) Close() { p.cl.Close() }

// Publish envía el evento y espera la confirmación de Kafka. Devuelve el evento enviado.
func (p *Publisher) Publish(ctx context.Context, topic string, data map[string]any, correlationID string) ([]byte, error) {
	value, key, err := Build(p.c, topic, p.source, correlationID, data, time.Now())
	if err != nil {
		return nil, err
	}
	rec := &kgo.Record{Topic: topic, Key: []byte(key), Value: value}
	if err := p.cl.ProduceSync(ctx, rec).FirstErr(); err != nil {
		return nil, err
	}
	return value, nil
}
