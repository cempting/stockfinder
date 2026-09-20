# Architecture

Stockfinder uses packages named after responsibilities rather than a generic
`core` package. A module should have one obvious owner and dependencies should
point toward reusable business logic, never back toward Streamlit.

## Package layout

```text
stockfinder/
├── presentation/       Streamlit shell and dashboard framework
├── infrastructure/     Runtime paths, configuration persistence, and storage
├── widgets/            Independently registered dashboard widgets
├── analysis.py         Market and security analysis
├── data.py             Provider access and market-universe loading
├── scan.py             Scan orchestration
├── screening.py        Candidate rules and ranking
├── portfolio.py        Portfolio calculations
└── models.py           Shared data models
```

### Presentation

`stockfinder.presentation` owns rendering and interaction:

- `ui.py` composes workspace pages and application services.
- `dashboard.py` parses dashboard configuration.
- `dashboard_renderer.py` lays out configured widgets.
- `dashboard_runtime.py` defines the service boundary supplied to widgets.
- `navigation.py` owns linked analysis context.
- `widget_registry.py` and `widget_help.py` support the widget plugin surface.

Presentation may import domain modules, infrastructure, and widgets. None of
those modules should import `presentation.ui`.

### Infrastructure

`stockfinder.infrastructure` owns process and persistence concerns:

- `runtime.py` resolves writable application paths.
- `config.py` validates and persists analysis configuration.
- `storage.py` owns SQLite, Parquet, JSON, and CSV persistence.

Infrastructure must not import presentation code. Domain and operational modules
may depend on infrastructure through these explicit modules.

### Widgets

`stockfinder.widgets` remains top-level because widgets are plugins registered
with the presentation framework, not private implementation details of the main
UI. A widget receives `WidgetSpec`, `AnalysisContext`, and `DashboardServices`;
it should not reach into the application shell.

## Compatibility imports

The former flat modules such as `stockfinder.ui`, `stockfinder.dashboard`,
`stockfinder.storage`, and `stockfinder.config` remain module-identity aliases.
Existing integrations and monkeypatch-based tests therefore continue to work,
while new production code should import from the canonical packages.

Compatibility aliases can be removed in a future major release after downstream
callers migrate.

## Placement rules

- Put Streamlit layout and interaction in `presentation/` or a widget.
- Put file, database, environment, and cache persistence in `infrastructure/`.
- Put calculations and filtering in domain modules that do not import Streamlit.
- Keep CLI orchestration modules at the package root when they are public entry
  points, but have them call domain and infrastructure services.
- Do not add a `core` package. If a module has no clear owner, clarify its
  responsibility before choosing a location.
