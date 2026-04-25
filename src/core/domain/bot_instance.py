from pydantic import UUID4, BaseModel, ConfigDict


class BotInstance(BaseModel):
    """Domain entity representing a bot instance (messenger integration)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID4 | None = None
    company_id: UUID4
    messenger_type: str  # TG / YM / MX
    token: str
    status: str = "active"  # active / inactive
    module_type: str = "finance"  # finance, estimator, hr, etc.
    config: dict | None = None  # module-specific configuration
