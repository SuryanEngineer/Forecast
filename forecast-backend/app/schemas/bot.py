from pydantic import BaseModel


class BotSeedResponse(BaseModel):
    population_before: int
    created: int
    population_after: int


class BotTickResponse(BaseModel):
    population: int
    active: int
    actions: int
    errors: int
