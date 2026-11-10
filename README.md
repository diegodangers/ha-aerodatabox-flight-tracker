# SkyLedger

Home Assistant flight tracking, travel history, notifications and airline reliability.

**Development/migration stage.** The user-visible integration name is SkyLedger.
The new internal domain is `skyledger`. **Do not install this migration branch on an existing installation yet.** Configuration-entry, persistent-history, service, and dashboard migrations are required before deployment.

## Native configuration

After installing and restarting, open Settings → Devices & Services → SkyLedger →
Configure to set approved phone, Alexa/media player and TV notification recipients
and Alexa quiet hours. These defaults apply to **new flights only**; existing
flight-specific recipient settings are preserved. New destinations are not
automatically approved. The Add Flight card no longer requires selecting recipients.

The schedule provider is currently AeroDataBox, and live tracking uses
Flightradar24. Provider independence is an architectural goal, not yet an
implemented provider-switching capability.

## Flights dashboard

The current user's Flights dashboard is a storage-mode Lovelace dashboard and is
**not automatically deployed** by the integration or by installing its Python
files. Existing dashboards remain as-is on upgrade. The optional Flight Manager
frontend is in `www/skyledger-flight-manager-card.js`. Copy it to
`/config/www/`, register it as a JavaScript module resource at
`/local/skyledger-flight-manager-card.js`, and add:

```yaml
type: custom:skyledger-flight-manager-card
title: Flight Manager
```

The rest of the existing Flights dashboard contains views/cards configured in
Home Assistant and is not bundled for automatic installation. A portable,
opt-in dashboard template is future work. Installing this integration must not
replace an existing user's Lovelace dashboard.

## Flight management

New installations use `skyledger` services. Existing `aerodatabox_flights` services remain on the old installation until migration, including `save_flight`, `delete_flight`, and
`set_flight_statistics_included`.
