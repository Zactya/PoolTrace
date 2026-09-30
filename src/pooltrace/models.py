"""Versioned public contracts. Rates are decimals; amounts are USD."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LoanMonth(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal["1.0"] = "1.0"
    loan_id: str = Field(min_length=1, max_length=80)
    pool_id: str = Field(min_length=1, max_length=80)
    period: date
    beginning_balance: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    ending_balance: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    scheduled_principal: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    prepayment: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    other_reduction: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=18, decimal_places=2
    )
    gross_rate: float = Field(ge=0, le=0.30)
    net_rate: float = Field(ge=0, le=0.30)
    remaining_months: int = Field(ge=1, le=480)
    age_months: int = Field(ge=0, le=600)
    refinance_rate: float = Field(ge=0, le=0.30)
    event: Literal["active", "prepaid", "liquidated", "repurchased"] = "active"
    provenance: Literal["synthetic", "user_supplied"] = "user_supplied"

    @model_validator(mode="after")
    def accounting(self):
        if self.period.day != 1:
            raise ValueError("period must be the first day of the reporting month")
        if self.net_rate > self.gross_rate:
            raise ValueError("net rate cannot exceed borrower rate")
        residual = (
            self.beginning_balance
            - self.ending_balance
            - self.scheduled_principal
            - self.prepayment
            - self.other_reduction
        )
        if abs(residual) > Decimal("0.02"):
            raise ValueError("balance identity does not reconcile within $0.02")
        if self.event in ("liquidated", "repurchased") and self.prepayment > 0:
            raise ValueError(
                "non-voluntary exit cannot be classified as voluntary prepayment"
            )
        if self.event != "active" and self.ending_balance != 0:
            raise ValueError("exit events must have zero ending balance")
        return self


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    cpr: float = Field(default=0.08, ge=0, le=0.8)
    discount_rate: float = Field(default=0.045, ge=0, le=0.25)
    market_price: float = Field(default=100.0, gt=20, le=200)
    volatility: float = Field(default=0.01, ge=0, le=0.08)
    paths: int = Field(default=128, ge=32, le=512)
    seed: int = Field(default=17, ge=0, le=2**32 - 1)

    @model_validator(mode="after")
    def paired_paths(self):
        if self.paths % 2:
            raise ValueError("paths must be even for antithetic sampling")
        return self


class IngestRequest(BaseModel):
    source: str = Field(default="canonical-upload", min_length=1, max_length=80)
    csv_text: str = Field(min_length=1, max_length=2_000_000)
    published_at: str | None = None


class ReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    pool_id: str
    source: str = Field(min_length=1, max_length=100)
    as_of: date
    price: float = Field(gt=0, le=300)
    wal: float = Field(ge=0, le=50)
    duration: float = Field(ge=-100, le=100)
    oas_bps: float | None = Field(default=None, ge=-5000, le=5000)
    cpr: float = Field(ge=0, le=0.8)
    discount_rate: float = Field(ge=0, le=0.25)
    conventions: str = Field(
        default="monthly-net-coupon;current-balance;flat-continuous;no-accrual",
        max_length=300,
    )
    duration_type: str = Field(default="fixed_cashflow_parallel_rate", max_length=80)


class PerformanceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    release: Literal["r47", "pre-r47"] = "r47"
    source: str = Field(default="freddie-sfll", min_length=1, max_length=80)


class BreakUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner: str = Field(min_length=1, max_length=80)
    status: Literal["open", "investigating", "resolved"]
    note: str = Field(min_length=3, max_length=1000)


class ToleranceUpdate(BaseModel):
    price: float = Field(ge=0, le=20, allow_inf_nan=False)
    wal: float = Field(ge=0, le=10, allow_inf_nan=False)
    duration: float = Field(ge=0, le=10, allow_inf_nan=False)
    oas_bps: float = Field(ge=0, le=1000, allow_inf_nan=False)
