"""Realistic upstream failures, injected into a staged batch for demos and tests."""

STAGE = "STAGE.YELLOW_TRIPS"
WHERE = "WHERE BATCH_ID = {b}"

SCENARIOS = {
    "duplicates": (
        "A retried job re-sent part of the batch",
        [f"INSERT INTO {STAGE} SELECT * FROM {STAGE} {WHERE} AND RANDOM() < 0.3"],
    ),
    "volume_drop": (
        "The source export was cut off partway",
        [f"DELETE FROM {STAGE} {WHERE} AND RANDOM() < 0.85"],
    ),
    "empty": (
        "The job ran but delivered nothing",
        [f"DELETE FROM {STAGE} {WHERE}"],
    ),
    "null_spike": (
        "A partner API started returning blanks",
        [f"UPDATE {STAGE} SET PASSENGER_COUNT = NULL, PULOCATIONID = NULL {WHERE} AND RANDOM() < 0.6"],
    ),
    "column_dropped": (
        "Upstream renamed a column, so it lands empty",
        [f"UPDATE {STAGE} SET TIP_AMOUNT = NULL {WHERE}"],
    ),
    "bad_values": (
        "Refund logic flipped the sign of fares",
        [f"UPDATE {STAGE} SET TOTAL_AMOUNT = -ABS(TOTAL_AMOUNT), FARE_AMOUNT = -ABS(FARE_AMOUNT) "
         f"{WHERE} AND RANDOM() < 0.4"],
    ),
    "unit_change": (
        "Upstream switched amounts from dollars to cents",
        [f"UPDATE {STAGE} SET TOTAL_AMOUNT = TOTAL_AMOUNT * 100, FARE_AMOUNT = FARE_AMOUNT * 100 {WHERE}"],
    ),
}


def inject(conn, batch_id: str, scenario: str) -> str:
    description, statements = SCENARIOS[scenario]
    for stmt in statements:
        conn.execute(stmt, {"b": batch_id})
    return description
