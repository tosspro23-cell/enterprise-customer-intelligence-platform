from dataclasses import dataclass


@dataclass(frozen=True)
class CustomerRecord:
    customer_id: str
    name: str
    segment: str
    language: str
    tenure_months: int


CUSTOMERS = {
    "C001": CustomerRecord("C001", "Sarah Chen", "PERSONAL", "en", 28),
    "C002": CustomerRecord("C002", "Alex Morgan", "PERSONAL", "en", 9),
}


class MockCustomerAPI:
    def get(self, customer_id: str) -> CustomerRecord:
        try:
            return CUSTOMERS[customer_id]
        except KeyError as exc:
            raise LookupError(f"unknown customer: {customer_id}") from exc
