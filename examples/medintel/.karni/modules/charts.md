## Saved charts (karni-charts, experimental)
- A chart people edit in the admin is a `Chart` row, never a page of code:
  a source resource, an x axis (a group), a y axis (metric and value), an
  optional z axis (stacked or series), default and allowed filters.
- The source must declare `class Karni: aggregate` on its model. The data
  comes from `GET /api/<source>/aggregate/` as the viewer, so the source's
  access applies. Never compute chart data in a view of your own.
- Draw one with `<SavedChart chart="<slug>" />` from `@karni/charts-ui`.
  API: `/api/charts/`, `/api/charts/<slug>/data/?<allowed filters>`.
- Setting: KARNI_CHARTS_READ (authenticated|public|granted), who reads the
  definitions.
