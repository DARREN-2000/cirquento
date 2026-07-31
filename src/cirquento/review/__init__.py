"""Human-in-the-loop review.

The classifier abstains rather than guessing when it is below the confidence
floor, and the entity resolver parks ambiguous supplier pairs instead of
merging them. Both are only defensible if the parked work actually goes
somewhere — otherwise "we abstain" is just a nicer word for "we drop data".
This package is where it goes.
"""

from cirquento.review.queue import ReviewItem, ReviewQueue

__all__ = ["ReviewItem", "ReviewQueue"]
