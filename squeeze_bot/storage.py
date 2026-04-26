from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, Float, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from squeeze_bot.config import Settings
from squeeze_bot.models import Decision, Opportunity, PositionMeta, Scores


class Base(DeclarativeBase):
    pass


class ScanLog(Base):
    __tablename__ = "scan_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    price: Mapped[float] = mapped_column(Float)
    composite_score: Mapped[float] = mapped_column(Float)
    acceleration_score: Mapped[float] = mapped_column(Float)
    action: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text)


class OrderLog(Base):
    __tablename__ = "order_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[str] = mapped_column(Text)


class TradeOutcome(Base):
    __tablename__ = "trade_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    entry_time: Mapped[datetime] = mapped_column(DateTime)
    exit_time: Mapped[datetime] = mapped_column(DateTime)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    pnl_pct: Mapped[float] = mapped_column(Float)
    entry_score: Mapped[float] = mapped_column(Float)
    entry_acceleration: Mapped[float] = mapped_column(Float)
    exit_reason: Mapped[str] = mapped_column(Text)


class PendingOrder(Base):
    __tablename__ = "pending_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    alpaca_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    payload_json: Mapped[str] = mapped_column(Text)


class PositionMetaRow(Base):
    __tablename__ = "position_metadata"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    entry_time: Mapped[datetime] = mapped_column(DateTime)
    entry_price: Mapped[float] = mapped_column(Float)
    peak_price: Mapped[float] = mapped_column(Float)
    entry_score: Mapped[float] = mapped_column(Float, default=0.0)
    entry_acceleration: Mapped[float] = mapped_column(Float, default=0.0)
    acceleration_decay_cycles: Mapped[int] = mapped_column(Integer, default=0)
    stop_price: Mapped[float] = mapped_column(Float, default=0.0)
    trailing_stop_pct: Mapped[float] = mapped_column(Float, default=0.0)


class BotState(Base):
    __tablename__ = "bot_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class OpportunityRow(Base):
    __tablename__ = "opportunities"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    source: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float)
    move_pct: Mapped[float] = mapped_column(Float, default=0.0)
    rvol: Mapped[float] = mapped_column(Float, default=0.0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class CandidateObservation(Base):
    __tablename__ = "candidate_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(64), default="")
    price: Mapped[float] = mapped_column(Float)
    composite_score: Mapped[float] = mapped_column(Float)
    acceleration_score: Mapped[float] = mapped_column(Float)
    action: Mapped[str] = mapped_column(String(32))
    return_1h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_4h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="")


class Storage:
    def __init__(self, settings: Settings):
        self.engine = create_engine(settings.database_url)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def log_scan(self, symbol: str, price: float, scores: Scores, decision: Decision, payload: dict) -> None:
        with Session(self.engine) as session:
            session.add(
                ScanLog(
                    symbol=symbol,
                    price=price,
                    composite_score=scores.composite,
                    acceleration_score=scores.acceleration,
                    action=decision.action.value,
                    reason=decision.reason,
                    payload_json=json.dumps(payload, default=str),
                )
            )
            session.commit()

    def log_order(self, symbol: str, side: str, quantity: float, price: float, status: str, payload: dict) -> None:
        with Session(self.engine) as session:
            session.add(
                OrderLog(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=price,
                    status=status,
                    payload_json=json.dumps(payload, default=str),
                )
            )
            session.commit()

    def trade_counts_today(self) -> tuple[int, int]:
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        with Session(self.engine) as session:
            rows = session.scalars(select(OrderLog).where(OrderLog.created_at >= start)).all()
            outcomes = session.scalars(select(TradeOutcome).where(TradeOutcome.exit_time >= start)).all()
        trade_statuses = {"dry_run", "submitted", "filled", "filled_reconciled"}
        trades = sum(1 for row in rows if row.side == "buy" and row.status in trade_statuses)
        losses = sum(1 for row in outcomes if row.pnl_pct <= 0)
        return trades, losses

    def add_pending_order(self, order_id: str, symbol: str, side: str, quantity: float, payload: dict) -> None:
        with Session(self.engine) as session:
            row = session.scalar(select(PendingOrder).where(PendingOrder.alpaca_order_id == order_id))
            if row is None:
                row = PendingOrder(
                    alpaca_order_id=order_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    status="pending",
                    payload_json=json.dumps(payload, default=str),
                )
                session.add(row)
            else:
                row.symbol = symbol
                row.side = side
                row.quantity = quantity
                row.status = "pending"
                row.payload_json = json.dumps(payload, default=str)
            session.commit()

    def record_trade_outcome(self, symbol: str, exit_price: float, quantity: float, exit_reason: str) -> None:
        meta = self.get_position_meta(symbol)
        if meta is None or meta.entry_price <= 0:
            return
        pnl_pct = ((exit_price - meta.entry_price) / meta.entry_price) * 100
        with Session(self.engine) as session:
            session.add(
                TradeOutcome(
                    symbol=symbol,
                    entry_time=meta.entry_time,
                    exit_time=datetime.now(UTC),
                    entry_price=meta.entry_price,
                    exit_price=exit_price,
                    quantity=quantity,
                    pnl_pct=pnl_pct,
                    entry_score=meta.entry_score,
                    entry_acceleration=meta.entry_acceleration,
                    exit_reason=exit_reason,
                )
            )
            session.commit()

    def update_pending_order(self, order_id: str, status: str, payload: dict | None = None) -> None:
        with Session(self.engine) as session:
            row = session.scalar(select(PendingOrder).where(PendingOrder.alpaca_order_id == order_id))
            if row:
                row.status = status
                if payload is not None:
                    row.payload_json = json.dumps(payload, default=str)
                session.commit()

    def open_pending_orders(self) -> list[PendingOrder]:
        with Session(self.engine) as session:
            return list(session.scalars(select(PendingOrder).where(PendingOrder.status == "pending")).all())

    def upsert_position_meta(self, meta: PositionMeta) -> None:
        with Session(self.engine) as session:
            session.merge(
                PositionMetaRow(
                    symbol=meta.symbol,
                    entry_time=meta.entry_time,
                    entry_price=meta.entry_price,
                    peak_price=meta.peak_price,
                    entry_score=meta.entry_score,
                    entry_acceleration=meta.entry_acceleration,
                    acceleration_decay_cycles=meta.acceleration_decay_cycles,
                    stop_price=meta.stop_price,
                    trailing_stop_pct=meta.trailing_stop_pct,
                )
            )
            session.commit()

    def get_position_meta(self, symbol: str) -> PositionMeta | None:
        with Session(self.engine) as session:
            row = session.get(PositionMetaRow, symbol)
            if row is None:
                return None
            return PositionMeta(
                symbol=row.symbol,
                entry_time=row.entry_time,
                entry_price=row.entry_price,
                peak_price=row.peak_price,
                entry_score=row.entry_score,
                entry_acceleration=row.entry_acceleration,
                acceleration_decay_cycles=row.acceleration_decay_cycles,
                stop_price=row.stop_price,
                trailing_stop_pct=row.trailing_stop_pct,
            )

    def update_position_meta_for_scan(self, symbol: str, price: float, acceleration_rising: bool) -> PositionMeta | None:
        with Session(self.engine) as session:
            row = session.get(PositionMetaRow, symbol)
            if row is None:
                return None
            row.peak_price = max(row.peak_price, price)
            row.acceleration_decay_cycles = 0 if acceleration_rising else row.acceleration_decay_cycles + 1
            session.commit()
            return PositionMeta(
                symbol=row.symbol,
                entry_time=row.entry_time,
                entry_price=row.entry_price,
                peak_price=row.peak_price,
                entry_score=row.entry_score,
                entry_acceleration=row.entry_acceleration,
                acceleration_decay_cycles=row.acceleration_decay_cycles,
                stop_price=row.stop_price,
                trailing_stop_pct=row.trailing_stop_pct,
            )

    def update_trailing_stop(self, symbol: str, trailing_stop_pct: float) -> None:
        with Session(self.engine) as session:
            row = session.get(PositionMetaRow, symbol)
            if row:
                row.trailing_stop_pct = trailing_stop_pct
                session.commit()

    def delete_position_meta(self, symbol: str) -> None:
        with Session(self.engine) as session:
            row = session.get(PositionMetaRow, symbol)
            if row:
                session.delete(row)
                session.commit()

    def set_state(self, key: str, value: dict) -> None:
        with Session(self.engine) as session:
            session.merge(BotState(key=key, value=json.dumps(value, default=str), updated_at=datetime.now(UTC)))
            session.commit()

    def upsert_opportunity(self, opportunity: Opportunity) -> None:
        with Session(self.engine) as session:
            row = session.get(OpportunityRow, opportunity.symbol)
            if row is None:
                row = OpportunityRow(symbol=opportunity.symbol)
                session.add(row)
            row.source = opportunity.source
            row.score = opportunity.score
            row.move_pct = opportunity.move_pct
            row.rvol = opportunity.rvol
            row.price = opportunity.price
            row.reason = opportunity.reason
            row.discovered_at = opportunity.discovered_at
            session.commit()

    def active_opportunities(self, ttl_minutes: int, limit: int) -> list[Opportunity]:
        cutoff = datetime.now(UTC) - timedelta(minutes=ttl_minutes)
        with Session(self.engine) as session:
            rows = session.scalars(
                select(OpportunityRow)
                .where(OpportunityRow.discovered_at >= cutoff)
                .order_by(OpportunityRow.score.desc(), OpportunityRow.discovered_at.desc())
                .limit(limit)
            ).all()
        return [
            Opportunity(
                symbol=row.symbol,
                source=row.source,
                score=row.score,
                move_pct=row.move_pct,
                rvol=row.rvol,
                price=row.price,
                reason=row.reason,
                discovered_at=row.discovered_at,
            )
            for row in rows
        ]

    def prune_opportunities(self, ttl_minutes: int) -> None:
        cutoff = datetime.now(UTC) - timedelta(minutes=ttl_minutes)
        with Session(self.engine) as session:
            rows = session.scalars(select(OpportunityRow).where(OpportunityRow.discovered_at < cutoff)).all()
            for row in rows:
                session.delete(row)
            session.commit()

    def record_candidate_observation(self, symbol: str, source: str, price: float, scores: Scores, decision: Decision, payload: dict) -> None:
        with Session(self.engine) as session:
            session.add(
                CandidateObservation(
                    symbol=symbol,
                    source=source,
                    price=price,
                    composite_score=scores.composite,
                    acceleration_score=scores.acceleration,
                    action=decision.action.value,
                    payload_json=json.dumps(payload, default=str),
                )
            )
            session.commit()

    def update_candidate_returns(self, symbol: str, current_price: float) -> None:
        if current_price <= 0:
            return
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=5)
        with Session(self.engine) as session:
            rows = session.scalars(
                select(CandidateObservation)
                .where(CandidateObservation.symbol == symbol)
                .where(CandidateObservation.observed_at >= cutoff)
            ).all()
            changed = False
            for row in rows:
                age = now - row.observed_at.replace(tzinfo=UTC)
                if row.price <= 0:
                    continue
                ret = ((current_price - row.price) / row.price) * 100
                if row.return_1h_pct is None and age >= timedelta(hours=1):
                    row.return_1h_pct = ret
                    changed = True
                if row.return_4h_pct is None and age >= timedelta(hours=4):
                    row.return_4h_pct = ret
                    changed = True
            if changed:
                session.commit()
