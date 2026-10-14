package schedule

import (
	"testing"
	"time"
)

func utc(s string) time.Time {
	t, err := time.Parse("2006-01-02 15:04", s)
	if err != nil {
		panic(err)
	}
	return t
}

func TestFranjas(t *testing.T) {
	s, err := Parse("22:30", "mon,tue,wed,thu,fri")
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct{ now, last, next string }{
		{"2026-10-14 09:00", "2026-10-13 22:30", "2026-10-14 22:30"}, // miércoles por la mañana
		{"2026-10-14 22:30", "2026-10-14 22:30", "2026-10-15 22:30"}, // justo en la franja
		{"2026-10-16 23:00", "2026-10-16 22:30", "2026-10-19 22:30"}, // viernes noche -> lunes
		{"2026-10-18 12:00", "2026-10-16 22:30", "2026-10-19 22:30"}, // domingo
		{"2026-10-19 08:00", "2026-10-16 22:30", "2026-10-19 22:30"}, // lunes antes de la hora
	} {
		now := utc(c.now)
		if got := s.LastDue(now); !got.Equal(utc(c.last)) {
			t.Errorf("LastDue(%s) = %s, se esperaba %s", c.now, got, c.last)
		}
		if got := s.Next(now); !got.Equal(utc(c.next)) {
			t.Errorf("Next(%s) = %s, se esperaba %s", c.now, got, c.next)
		}
	}
	if RunID(utc("2026-10-16 22:30")) != "daily-2026-10-16" {
		t.Error("run_id")
	}
}

func TestParseErrores(t *testing.T) {
	for _, c := range [][2]string{{"25:00", "mon"}, {"22:30", "lunes"}, {"2230", "mon"}} {
		if _, err := Parse(c[0], c[1]); err == nil {
			t.Errorf("Parse(%q, %q) debería fallar", c[0], c[1])
		}
	}
}
