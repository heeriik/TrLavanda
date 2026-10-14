module github.com/heeriik/TrLavanda/services/scheduler

go 1.27.0

require github.com/heeriik/TrLavanda/libs/go v0.0.0

require (
	github.com/klauspost/compress v1.20.3 // indirect
	github.com/pierrec/lz4/v4 v4.1.33 // indirect
	github.com/santhosh-tekuri/jsonschema/v6 v6.0.3 // indirect
	github.com/twmb/franz-go v1.22.2 // indirect
	github.com/twmb/franz-go/pkg/kmsg v1.15.0 // indirect
	golang.org/x/text v0.41.0 // indirect
)

replace github.com/heeriik/TrLavanda/libs/go => ../../libs/go
