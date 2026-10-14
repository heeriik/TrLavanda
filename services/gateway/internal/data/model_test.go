package data

import (
	"math"
	"testing"
)

func TestPyTitle(t *testing.T) {
	for in, want := range map[string]string{
		"AAA ENERGY INC":    "Aaa Energy Inc",
		"MOODY'S CORP /DE/": "Moody'S Corp /De/",
		"3M CO":             "3M Co",
		"AT&T INC.":         "At&T Inc.",
		"o'reilly":          "O'Reilly",
		"":                  "",
	} {
		if got := PyTitle(in); got != want {
			t.Errorf("PyTitle(%q) = %q, se esperaba %q", in, got, want)
		}
	}
}

func n(v float64) Num { return Num{V: v, OK: true} }

func TestMedianaComoPolars(t *testing.T) {
	nan := math.NaN()
	cases := []struct {
		in   []Num
		want float64 // NaN = se espera NaN; -1 = se espera nulo
	}{
		{[]Num{n(1), n(nan), n(3)}, 3}, // NaN se ordena al final
		{[]Num{n(1), n(nan)}, nan},     // la media de los dos centrales es NaN
		{[]Num{n(1), {}, n(3)}, 2},     // los nulos se ignoran
		{[]Num{{}, {}}, -1},            // todo nulo: nulo
		{[]Num{n(4), n(1), n(3), n(2)}, 2.5},
	}
	for _, c := range cases {
		got := Median(c.in)
		switch {
		case c.want == -1:
			if got.OK {
				t.Errorf("Median(%v) = %v, se esperaba nulo", c.in, got)
			}
		case math.IsNaN(c.want):
			if !got.OK || !math.IsNaN(got.V) {
				t.Errorf("Median(%v) = %v, se esperaba NaN", c.in, got)
			}
		case !got.OK || got.V != c.want:
			t.Errorf("Median(%v) = %v, se esperaba %v", c.in, got, c.want)
		}
	}
}
