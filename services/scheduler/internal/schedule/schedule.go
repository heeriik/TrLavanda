// Package schedule calcula las franjas de ejecución: una hora UTC fija en ciertos días.
package schedule

import (
	"fmt"
	"strings"
	"time"
)

type Schedule struct {
	Hour, Minute int
	Days         map[time.Weekday]bool
}

var dayNames = map[string]time.Weekday{
	"sun": time.Sunday, "mon": time.Monday, "tue": time.Tuesday, "wed": time.Wednesday,
	"thu": time.Thursday, "fri": time.Friday, "sat": time.Saturday,
}

// Parse: at = "22:30" (UTC), days = "mon,tue,wed,thu,fri".
func Parse(at, days string) (Schedule, error) {
	t, err := time.Parse("15:04", at)
	if err != nil {
		return Schedule{}, fmt.Errorf("hora %q: formato HH:MM", at)
	}
	s := Schedule{Hour: t.Hour(), Minute: t.Minute(), Days: map[time.Weekday]bool{}}
	for _, d := range strings.Split(days, ",") {
		wd, ok := dayNames[strings.ToLower(strings.TrimSpace(d))]
		if !ok {
			return Schedule{}, fmt.Errorf("día %q: use sun,mon,tue,wed,thu,fri,sat", d)
		}
		s.Days[wd] = true
	}
	if len(s.Days) == 0 {
		return Schedule{}, fmt.Errorf("ningún día")
	}
	return s, nil
}

func (s Schedule) at(day time.Time) time.Time {
	y, m, d := day.UTC().Date()
	return time.Date(y, m, d, s.Hour, s.Minute, 0, 0, time.UTC)
}

// LastDue: la franja más reciente que ya debería haberse ejecutado (<= now).
func (s Schedule) LastDue(now time.Time) time.Time {
	for i := 0; i <= 7; i++ {
		slot := s.at(now.AddDate(0, 0, -i))
		if s.Days[slot.Weekday()] && !slot.After(now) {
			return slot
		}
	}
	panic("inalcanzable: hay al menos un día en la semana")
}

// Next: la siguiente franja estrictamente posterior a now.
func (s Schedule) Next(now time.Time) time.Time {
	for i := 0; i <= 7; i++ {
		slot := s.at(now.AddDate(0, 0, i))
		if s.Days[slot.Weekday()] && slot.After(now) {
			return slot
		}
	}
	panic("inalcanzable: hay al menos un día en la semana")
}

// RunID: identificador determinista de una franja. Publicarlo dos veces no hace daño: ingest
// ignora los run_id que ya ha procesado.
func RunID(slot time.Time) string { return "daily-" + slot.Format(time.DateOnly) }
