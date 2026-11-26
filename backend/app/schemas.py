from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl, ConfigDict

class FieldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    data_type: str = "string"
    required: bool = True
    example_value: str | None = None

class SiteCreate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    url: HttpUrl
    run_frequency: str = "manual"
    fields: list[FieldCreate] = []

class FieldOut(BaseModel):
    id: int
    name: str
    data_type: str
    required: bool
    example_value: str | None
    model_config = ConfigDict(from_attributes=True)

class SiteOut(BaseModel):
    id: int
    name: str
    url: str
    run_frequency: str
    status: str
    created_at: datetime
    fields: list[FieldOut]
    model_config = ConfigDict(from_attributes=True)

class ExtractionRequest(BaseModel):
    config_id: int = Field(gt=0)
    max_pages: int | None = Field(default=None, ge=1, le=100)
    extract_details: bool | None = None
    max_detail_pages: int | None = Field(default=None, ge=1, le=500)


class ExtractionResponse(BaseModel):
    message: str
    run_id: int
    config_id: int
    pages_crawled: int
    record_count: int
    diagnostics: dict
    records: list[dict]
