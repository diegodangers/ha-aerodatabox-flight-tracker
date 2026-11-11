# SkyLedger domain migration — deployment checklist

Do not deploy `feature/skyledger-domain` until the following preflight passes.
The existing Home Assistant installation currently uses `aerodatabox_flights`.

## Known consumers (verified 2026-11-10)

- Config entry: `01M62QA3CCD6TTXR3H80MKT2WX` (must retain this ID)
- Existing flight sensors and `sensor.flights_tracked`: retain entity IDs and unique IDs
- Dashboard `upcoming-flights`, Manage view: `custom:aerodatabox-flight-delete-card`
- Dashboard `skyledger-legacy-backup`: same old card
- Four legacy blueprint automations: `automation.aerodatabox_flight_tracker_flight_and_date_3` through `_6`; their blueprint file may invoke legacy services
- The installed dashboard JavaScript resource `/local/aerodatabox-flight-delete-card.js` may still be referenced; inspect resource registry separately

## Offline migration sequence (not yet performed)

1. Make a complete Home Assistant backup and preserve the old integration directory.
2. Verify all YAML, storage-mode dashboard, blueprint, script, automation, and custom-card consumers of `aerodatabox_flights`. The audit above is not exhaustive.
3. Stop Home Assistant Core. Do not run migration against a live instance.
4. Run `python3 scripts/migrate_skyledger_domain.py --config /config` (dry run).
5. Review the entry ID, entity count and flight count; compare with the backup.
6. Install `custom_components/skyledger` and the renamed frontend card, then run the migration with `--apply` **while Core is stopped**.
7. Restart Core and verify history, sensors, service registrations and API configuration.
8. Update dashboard cards/resources and any active automations from `aerodatabox_flights.*` to `skyledger.*`, only after the new services exist. Legacy blueprint automations require separate review.
9. Verify all consumers, no duplicates, and statistics; only then remove old integration files.
10. Keep the migration backup until all checks pass.

## Rollback

Stop Core, restore the three original storage files from the migration backup,
remove `.storage/skyledger.history` only after preserving it, reinstall the
original `custom_components/aerodatabox_flights`, then restart. Restore any
dashboard/resource edits from their separate backups.

**Do not perform a blind search-and-replace on `.storage` or rename entity IDs.**
