from pydantic import BaseModel, Field


class DashboardLink(BaseModel):
    login_url: str = Field(description="Open this address in a browser to reach the dashboards.")
    expires_in: int = Field(description="Seconds the link stays valid. It works once.")
