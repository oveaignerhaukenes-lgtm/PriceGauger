# Ownership implementation note

The runtime now uses its exact assigned resource boundary for ownership. Conflicting observed state retires stale expectations so the following cycle starts from current observed state.