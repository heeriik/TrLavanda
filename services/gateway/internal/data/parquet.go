package data

import (
	"bytes"
	"context"
	"fmt"
	"math"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/apache/arrow-go/v18/arrow/array"
	"github.com/apache/arrow-go/v18/arrow/memory"
	"github.com/apache/arrow-go/v18/parquet/file"
	"github.com/apache/arrow-go/v18/parquet/pqarrow"
)

// Num es un número que puede faltar. Distingue "nulo" (OK=false: no hay dato) de NaN (OK=true
// y V=NaN), igual que Polars: las medianas ignoran los nulos pero no los NaN.
type Num struct {
	V  float64
	OK bool
}

// Usable: hay dato y es un número finito (lo que la API devuelve; si no, null).
func (n Num) Usable() bool { return n.OK && !math.IsNaN(n.V) && !math.IsInf(n.V, 0) }

// table son las columnas pedidas de un Parquet, ya convertidas a tipos de Go.
type table struct {
	n    int
	cols map[string]arrow.Array // una por columna, concatenando todos los lotes
}

// readParquet lee solo las columnas `names` (las que no existan dan error).
func readParquet(b []byte, names []string) (*table, error) {
	pf, err := file.NewParquetReader(bytes.NewReader(b))
	if err != nil {
		return nil, err
	}
	defer pf.Close()
	fr, err := pqarrow.NewFileReader(pf, pqarrow.ArrowReadProperties{BatchSize: 1 << 16}, memory.DefaultAllocator)
	if err != nil {
		return nil, err
	}
	schema, err := fr.Schema()
	if err != nil {
		return nil, err
	}
	var idx []int
	for _, name := range names {
		fi := schema.FieldIndices(name)
		if len(fi) == 0 {
			return nil, fmt.Errorf("falta la columna %q", name)
		}
		idx = append(idx, fi[0])
	}
	tbl, err := fr.ReadTable(context.Background())
	if err != nil {
		return nil, err
	}
	defer tbl.Release()
	t := &table{n: int(tbl.NumRows()), cols: map[string]arrow.Array{}}
	for i, name := range names {
		chunks := tbl.Column(idx[i]).Data().Chunks()
		arr, err := array.Concatenate(chunks, memory.DefaultAllocator)
		if err != nil {
			return nil, fmt.Errorf("columna %q: %w", name, err)
		}
		t.cols[name] = arr
	}
	return t, nil
}

func (t *table) release() {
	for _, a := range t.cols {
		a.Release()
	}
}

type stringArray interface {
	IsNull(int) bool
	Value(int) string
}

func (t *table) strings(name string) ([]string, []bool, error) {
	a, ok := t.cols[name].(stringArray) // String, LargeString o StringView (según quién escribió el Parquet)
	if !ok {
		return nil, nil, fmt.Errorf("columna %q: se esperaba texto, es %s", name, t.cols[name].DataType())
	}
	out, valid := make([]string, t.n), make([]bool, t.n)
	for i := range t.n {
		if !a.IsNull(i) {
			out[i], valid[i] = a.Value(i), true
		}
	}
	return out, valid, nil
}

func (t *table) dates(name string) ([]int32, error) {
	a, ok := t.cols[name].(*array.Date32)
	if !ok {
		return nil, fmt.Errorf("columna %q: se esperaba fecha, es %s", name, t.cols[name].DataType())
	}
	out := make([]int32, t.n)
	for i := range t.n {
		if a.IsNull(i) {
			return nil, fmt.Errorf("columna %q: fecha nula en la fila %d", name, i)
		}
		out[i] = int32(a.Value(i))
	}
	return out, nil
}

func (t *table) nums(name string) ([]Num, error) {
	out := make([]Num, t.n)
	get := func(i int) (float64, bool) { return 0, false }
	switch a := t.cols[name].(type) {
	case *array.Float64:
		get = func(i int) (float64, bool) { return a.Value(i), !a.IsNull(i) }
	case *array.Float32:
		get = func(i int) (float64, bool) { return float64(a.Value(i)), !a.IsNull(i) }
	case *array.Int64:
		get = func(i int) (float64, bool) { return float64(a.Value(i)), !a.IsNull(i) }
	case *array.Int32:
		get = func(i int) (float64, bool) { return float64(a.Value(i)), !a.IsNull(i) }
	case *array.Uint32:
		get = func(i int) (float64, bool) { return float64(a.Value(i)), !a.IsNull(i) }
	case *array.Uint64:
		get = func(i int) (float64, bool) { return float64(a.Value(i)), !a.IsNull(i) }
	case *array.Null: // columna entera nula
	default:
		return nil, fmt.Errorf("columna %q: se esperaba número, es %s", name, a.DataType())
	}
	for i := range t.n {
		v, ok := get(i)
		out[i] = Num{V: v, OK: ok}
	}
	return out, nil
}
