# Life entity dossier

Use `schemas/lifedossier-v1.json` to prepare an owner-selected dossier for a home, vehicle,
pet, device, or other entity. Import it using `cairn life import` and review/apply its proposal.

- Stable entity alias and descriptive title
- Authoritative document IDs, source/evidence hashes, and exact locators
- Service events with dates, descriptions, and document references
- Warranty and renewal terms with dates and supporting references
- Procedure references
- Review-date metadata
- Owner decisions, separately proposed/adopted and linked to the entity

A revision appends sourced history and retains earlier assertions. Omitted earlier events
do not delete them. Review conflicting terms explicitly. A review date does not create a
reminder: external calendars and task systems remain authoritative for scheduled actions.
