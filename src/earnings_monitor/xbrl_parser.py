"""
Lightweight XBRL / inline-XBRL parser for NSE integrated financial filings.

Goals:
- Parse XML and inline-XBRL documents into normalized financial concepts.
- Prefer quarter-specific facts using contextRef / instant contexts.
- Fall back gracefully when only partial tagging is available.

This is not a full taxonomy engine, but it is a real XBRL fact extractor.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

XBRL_NAMESPACES = {
    "xbrli": "http://www.xbrl.org/2003/instance",
    "ix": "http://www.xbrl.org/2013/inlineXBRL",
    "link": "http://www.xbrl.org/2003/linkbase",
}

CONCEPT_ALIASES = {
    "revenue": [
        "RevenueFromOperations",
        "RevenueFromOperationsGross",
        "RevenueFromOperationsNet",
        "Revenue",
        "IncomeFromOperations",
        "NetSales",
        "SalesRevenueNet",
        "TotalRevenueFromOperations",
        "RevenueFromSaleOfProducts",
    ],
    "total_income": [
        "TotalIncome",
        "Income",
        "TotalRevenue",
        "TotalIncomeFromOperations",
    ],
    "pat": [
        "ProfitLossForPeriod",
        "ProfitAfterTax",
        "ProfitForPeriod",
        "ProfitLossAttributableToOwnersOfParent",
        "NetProfitLoss",
        "ProfitAfterTaxForPeriod",
    ],
    "pbt": [
        "ProfitBeforeTax",
        "ProfitLossBeforeTax",
    ],
    "finance_cost": [
        "FinanceCosts",
        "FinanceCost",
    ],
    "depreciation": [
        "DepreciationAndAmortisationExpense",
        "DepreciationAmortisationAndImpairmentExpense",
        "DepreciationExpense",
        "AmortisationExpense",
    ],
    "tax": [
        "TaxExpense",
        "CurrentTax",
        "IncomeTaxExpense",
    ],
    "eps_diluted": [
        "DilutedEarningsLossPerShare",
        "DilutedEarningsPerShare",
        "DilutedEPS",
    ],
    "eps_basic": [
        "BasicEarningsLossPerShare",
        "BasicEarningsPerShare",
        "BasicEPS",
    ],
    "operating_profit": [
        "ProfitBeforeFinanceCostsTaxDepreciationAndAmortisationExpense",
        "OperatingProfit",
        "ProfitBeforeDepreciationInterestAndTax",
        "EarningsBeforeInterestTaxDepreciationAndAmortisation",
        "EBITDA",
    ],
    "exceptional_items": [
        "ExceptionalItems",
        "ExceptionalItem",
    ],
}


@dataclass
class ContextInfo:
    context_id: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    instant: Optional[str] = None

    @property
    def is_duration(self) -> bool:
        return bool(self.start_date and self.end_date)


@dataclass
class Fact:
    concept: str
    value: Optional[float]
    raw_value: str
    context_ref: Optional[str]
    unit_ref: Optional[str]
    decimals: Optional[str]
    source: str


class XBRLParser:
    def __init__(self) -> None:
        self.contexts: Dict[str, ContextInfo] = {}
        self.facts: List[Fact] = []

    def parse_bytes(self, payload: bytes, source_name: str = "document") -> Dict[str, Optional[float]]:
        docs = self._expand_payload(payload)
        for doc_name, doc_bytes in docs:
            self._parse_document(doc_bytes, source=f"{source_name}:{doc_name}")
        return self._normalize_metrics()

    def _expand_payload(self, payload: bytes) -> List[Tuple[str, bytes]]:
        if payload[:2] == b"PK":
            docs = []
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                for name in zf.namelist():
                    lower = name.lower()
                    if lower.endswith((".xml", ".xhtml", ".html", ".htm", ".xbrl")):
                        docs.append((name, zf.read(name)))
            return docs
        return [("payload", payload)]

    def _parse_document(self, payload: bytes, source: str) -> None:
        text = payload.decode("utf-8", errors="ignore").strip()
        if not text:
            return
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            logger.warning("XBRL parse error for %s", source)
            return

        self._collect_contexts(root)
        self._collect_standard_facts(root, source)
        self._collect_inline_facts(root, source)

    def _collect_contexts(self, root: ET.Element) -> None:
        for ctx in root.findall('.//{http://www.xbrl.org/2003/instance}context'):
            ctx_id = ctx.attrib.get('id')
            if not ctx_id:
                continue
            period = ctx.find('{http://www.xbrl.org/2003/instance}period')
            start_date = end_date = instant = None
            if period is not None:
                sd = period.find('{http://www.xbrl.org/2003/instance}startDate')
                ed = period.find('{http://www.xbrl.org/2003/instance}endDate')
                ins = period.find('{http://www.xbrl.org/2003/instance}instant')
                start_date = sd.text.strip() if sd is not None and sd.text else None
                end_date = ed.text.strip() if ed is not None and ed.text else None
                instant = ins.text.strip() if ins is not None and ins.text else None
            self.contexts[ctx_id] = ContextInfo(ctx_id, start_date, end_date, instant)

    def _collect_standard_facts(self, root: ET.Element, source: str) -> None:
        for elem in root.iter():
            if not isinstance(elem.tag, str) or elem.tag.startswith('{http://www.xbrl.org/2013/inlineXBRL}'):
                continue
            context_ref = elem.attrib.get('contextRef')
            if not context_ref:
                continue
            concept = self._local_name(elem.tag)
            raw_value = (elem.text or '').strip()
            fact = Fact(
                concept=concept,
                value=self._coerce_value(raw_value, elem.attrib),
                raw_value=raw_value,
                context_ref=context_ref,
                unit_ref=elem.attrib.get('unitRef'),
                decimals=elem.attrib.get('decimals'),
                source=source,
            )
            self.facts.append(fact)

    def _collect_inline_facts(self, root: ET.Element, source: str) -> None:
        for tag in ('nonFraction', 'nonNumeric'):
            path = f'.//{{http://www.xbrl.org/2013/inlineXBRL}}{tag}'
            for elem in root.findall(path):
                name = elem.attrib.get('name', '')
                if not name:
                    continue
                raw_value = ''.join(elem.itertext()).strip()
                fact = Fact(
                    concept=self._local_name(name),
                    value=self._coerce_value(raw_value, elem.attrib),
                    raw_value=raw_value,
                    context_ref=elem.attrib.get('contextRef'),
                    unit_ref=elem.attrib.get('unitRef'),
                    decimals=elem.attrib.get('decimals'),
                    source=source,
                )
                self.facts.append(fact)

    def _normalize_metrics(self) -> Dict[str, Optional[float]]:
        out = {
            'revenue': self._best_fact_for_aliases(CONCEPT_ALIASES['revenue']),
            'total_income': self._best_fact_for_aliases(CONCEPT_ALIASES['total_income']),
            'pat': self._best_fact_for_aliases(CONCEPT_ALIASES['pat']),
            'pbt': self._best_fact_for_aliases(CONCEPT_ALIASES['pbt']),
            'finance_cost': self._best_fact_for_aliases(CONCEPT_ALIASES['finance_cost']),
            'depreciation': self._best_fact_for_aliases(CONCEPT_ALIASES['depreciation']),
            'tax': self._best_fact_for_aliases(CONCEPT_ALIASES['tax']),
            'eps_diluted': self._best_fact_for_aliases(CONCEPT_ALIASES['eps_diluted']),
            'eps_basic': self._best_fact_for_aliases(CONCEPT_ALIASES['eps_basic']),
            'operating_profit': self._best_fact_for_aliases(CONCEPT_ALIASES['operating_profit']),
            'exceptional_items': self._best_fact_for_aliases(CONCEPT_ALIASES['exceptional_items']),
        }

        if out['operating_profit'] is None:
            candidates = [out.get('pbt'), out.get('finance_cost'), out.get('depreciation')]
            if candidates[0] is not None and candidates[1] is not None and candidates[2] is not None:
                out['operating_profit'] = candidates[0] + candidates[1] + candidates[2]

        if out['revenue'] is None:
            out['revenue'] = out.get('total_income')

        if out['operating_profit'] is not None and out['revenue'] not in (None, 0):
            out['ebitda_margin_pct'] = round((out['operating_profit'] / out['revenue']) * 100, 2)
        else:
            out['ebitda_margin_pct'] = None

        if out['pat'] is not None and out['revenue'] not in (None, 0):
            out['pat_margin_pct'] = round((out['pat'] / out['revenue']) * 100, 2)
        else:
            out['pat_margin_pct'] = None

        out['xbrl_found'] = any(v is not None for k, v in out.items() if k != 'xbrl_found')
        return out

    def _best_fact_for_aliases(self, aliases: List[str]) -> Optional[float]:
        candidates = []
        alias_set = {a.lower() for a in aliases}
        for fact in self.facts:
            if fact.value is None:
                continue
            if fact.concept.lower() in alias_set:
                score = self._context_score(fact.context_ref)
                candidates.append((score, fact.value))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def _context_score(self, context_ref: Optional[str]) -> Tuple[int, int]:
        ctx = self.contexts.get(context_ref or '')
        if not ctx:
            return (0, 0)
        if ctx.is_duration:
            try:
                end = ctx.end_date or ''
                return (2, int(re.sub(r'\D', '', end) or '0'))
            except Exception:
                return (2, 0)
        if ctx.instant:
            try:
                return (1, int(re.sub(r'\D', '', ctx.instant) or '0'))
            except Exception:
                return (1, 0)
        return (0, 0)

    @staticmethod
    def _coerce_value(raw: str, attrs: Dict[str, str]) -> Optional[float]:
        if raw is None:
            return None
        s = raw.strip()
        if not s:
            return None
        s = s.replace(',', '').replace('₹', '').replace('%', '')
        s = s.replace('(', '-').replace(')', '')
        sign = attrs.get('sign')
        scale = attrs.get('scale')
        try:
            value = float(s)
            if sign == '-':
                value = -abs(value)
            if scale and re.fullmatch(r'-?\d+', scale):
                value *= 10 ** int(scale)
            return value
        except Exception:
            return None

    @staticmethod
    def _local_name(tag: str) -> str:
        if '}' in tag:
            return tag.split('}', 1)[1]
        if ':' in tag:
            return tag.split(':', 1)[1]
        return tag
