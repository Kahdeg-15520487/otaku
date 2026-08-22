"""The operations over the nucleus — one ops class per table group,
each built on a `Database`. A level above `database`/`schema` on
purpose: the nucleus owns opening, sealing, and the ladder; these own
what the rows MEAN."""
