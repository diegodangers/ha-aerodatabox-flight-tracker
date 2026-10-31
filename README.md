# ha-aerodatabox-flight-tracker
AeroDataBox flight tracking and travel history integration for Home Assistant

## Saved-flight delete card (development branch)

The integration includes a frontend Lovelace card at `www/aerodatabox-flight-delete-card.js`.
It lists current saved flight sensors and deletes **only the selected flight** via the
existing `aerodatabox_flights.delete_flight` service. Each deletion requires a
confirmation showing the flight, departure date, and route. Deletion permanently
removes its saved history and recalculates statistics. It does **not** issue an
FR24 removal request; a flight-number-only removal could affect another day's
flight. Manage FR24 tracking separately.

With Home Assistant Terminal & SSH, from the **extracted development branch**:

```sh
mkdir -p /config/www
cp /tmp/ha-aerodatabox-flight-tracker-feature-flight-history/www/aerodatabox-flight-delete-card.js /config/www/
```

In Home Assistant **Settings → Dashboards → Resources**, add a **JavaScript module**
resource at `/local/aerodatabox-flight-delete-card.js`. (If Resources are hidden,
enable Advanced Mode for your Home Assistant user.) Then add a **Manual** card to
the Flights dashboard:

```yaml
type: custom:aerodatabox-flight-delete-card
title: Manage saved flights
```

The standard development-branch integration install copies
`custom_components/aerodatabox_flights` only; it does **not** automatically
install this separate frontend resource. No HACS installation is necessary.
