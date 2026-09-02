"""The shared crypto primitives — protected: they hold no keys and take
no decisions; the two planes (`crypto.data`, `crypto.keys`) are the
package's surface, and nothing outside it imports from here."""
