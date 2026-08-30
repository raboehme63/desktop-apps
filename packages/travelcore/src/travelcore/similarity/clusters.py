"""Stack and group clusters. Originals are never deleted."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.database.models import Photo, SimilarityGroup, SimilarityGroupMember, SourceFile
from travelcore.exceptions import ProjectError
from travelcore.media.types import FileKind
from travelcore.similarity.types import ClusterStatus, ClusterType, SimilarityKind, SimilarityMethod

SCENE_WINDOW = timedelta(seconds=30)
_MEDIA_KINDS = (FileKind.PHOTO.value, FileKind.VIDEO.value)
_STAT_KINDS = (FileKind.PHOTO.value, FileKind.VIDEO.value, FileKind.GPS.value)
_REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ClusterMarks:
    stack_id: int | None = None
    stack_size: int = 0
    is_stack_key: bool = False
    group_id: int | None = None
    group_size: int = 0
    is_group_key: bool = False
    group_status: str | None = None
    hidden: bool = False


@dataclass(frozen=True, slots=True)
class ClusterOverlay:
    hidden: frozenset[int]
    marks: dict[int, ClusterMarks]

    def for_source(self, source_file_id: int) -> ClusterMarks:
        return self.marks.get(source_file_id, ClusterMarks())

    def is_hidden(self, source_file_id: int) -> bool:
        return source_file_id in self.hidden


@dataclass(frozen=True, slots=True)
class MediaStats:
    imported: int = 0
    gallery: int = 0
    rejected: int = 0
    pool: int = 0
    stacks: int = 0
    stack_hidden: int = 0
    groups: int = 0
    hidden: int = 0

    def format_line(self) -> str:
        return (
            f"Importiert {self.imported} · Galerie {self.gallery} · "
            f"Aussortiert {self.rejected} · Pool {self.pool} · "
            f"Dubletten {self.stacks} / {self.stack_hidden} · "
            f"Gruppen {self.groups} · Deaktiviert {self.hidden}"
        )


@dataclass(frozen=True, slots=True)
class ClusterRecord:
    id: int
    cluster_type: str
    status: str
    origin: str
    member_ids: tuple[int, ...]
    key_ids: tuple[int, ...]


def stack_key_score(row: SourceFile) -> tuple[int, int, int, int, int]:
    """Higher is better. WhatsApp-looking names lose against camera originals."""

    pixels = (row.width or 0) * (row.height or 0)
    has_camera = 1 if row.camera else 0
    has_gps = 1 if row.gps_latitude is not None and row.gps_longitude is not None else 0
    whatsapp = 1 if _looks_like_whatsapp(row.filename) else 0
    return (pixels, has_camera, has_gps, row.size_bytes, -whatsapp)


def _looks_like_whatsapp(filename: str) -> bool:
    upper = filename.upper()
    return "WA" in upper.split(".")[0] or "WHATSAPP" in upper


def load_cluster_overlay(session: Session, project_id: int) -> ClusterOverlay:
    groups = list(session.scalars(select(SimilarityGroup).where(SimilarityGroup.project_id == project_id)))
    marks: dict[int, ClusterMarks] = {}
    hidden: set[int] = set()
    for group in groups:
        members = list(group.members)
        if not members:
            continue
        size = len(members)
        member_ids = [item.source_file_id for item in members]
        if group.cluster_type == ClusterType.STACK:
            if group.status != ClusterStatus.ACCEPTED:
                continue
            key_ids = {item.source_file_id for item in members if item.is_key}
            for source_id in member_ids:
                is_key = source_id in key_ids
                if not is_key:
                    hidden.add(source_id)
                previous = marks.get(source_id, ClusterMarks())
                marks[source_id] = ClusterMarks(
                    stack_id=group.id,
                    stack_size=size,
                    is_stack_key=is_key,
                    group_id=previous.group_id,
                    group_size=previous.group_size,
                    is_group_key=previous.is_group_key,
                    group_status=previous.group_status,
                    hidden=not is_key or previous.hidden,
                )
            continue
        if group.cluster_type != ClusterType.GROUP or group.status == ClusterStatus.DISMISSED:
            continue
        accepted = group.status == ClusterStatus.ACCEPTED
        key_ids = {item.source_file_id for item in members if item.is_key} if accepted else set()
        for source_id in member_ids:
            is_key = source_id in key_ids
            if accepted and not is_key:
                hidden.add(source_id)
            previous = marks.get(source_id, ClusterMarks())
            marks[source_id] = ClusterMarks(
                stack_id=previous.stack_id,
                stack_size=previous.stack_size,
                is_stack_key=previous.is_stack_key,
                group_id=group.id,
                group_size=size,
                is_group_key=is_key,
                group_status=group.status,
                hidden=previous.hidden or (accepted and not is_key),
            )
    return ClusterOverlay(hidden=frozenset(hidden), marks=marks)


def load_cluster(session: Session, cluster_id: int) -> ClusterRecord:
    group = session.get(SimilarityGroup, cluster_id)
    if group is None:
        raise ProjectError("Stapel oder Gruppe wurde nicht gefunden.")
    members = sorted(group.members, key=lambda item: item.id)
    return ClusterRecord(
        id=group.id,
        cluster_type=group.cluster_type,
        status=group.status,
        origin=group.origin,
        member_ids=tuple(item.source_file_id for item in members),
        key_ids=tuple(
            item.source_file_id
            for item in members
            if item.is_key and group.status == ClusterStatus.ACCEPTED
        ),
    )


def accept_exact_stacks(session: Session, project_id: int) -> int:
    """Group identical SHA-256 copies into accepted stacks. Returns new or updated stacks."""

    rows = list(
        session.scalars(
            select(SourceFile).where(
                SourceFile.project_id == project_id,
                SourceFile.file_kind.in_(_MEDIA_KINDS),
                SourceFile.sha256.is_not(None),
            )
        )
    )
    by_hash: dict[str, list[SourceFile]] = defaultdict(list)
    for row in rows:
        if row.sha256:
            by_hash[row.sha256].append(row)
    stacked = _source_ids_in_type(session, project_id, ClusterType.STACK)
    changed = 0
    for files in by_hash.values():
        if len(files) < 2:
            continue
        ids = {row.id for row in files}
        existing_id = next((stacked[item_id] for item_id in ids if item_id in stacked), None)
        if existing_id is not None:
            if _add_missing_stack_members(session, existing_id, files):
                stacked.update({row.id: existing_id for row in files})
                changed += 1
            continue
        group = SimilarityGroup(
            project_id=project_id,
            kind=SimilarityKind.EXACT.value,
            method=SimilarityMethod.SHA256.value,
            cluster_type=ClusterType.STACK.value,
            status=ClusterStatus.ACCEPTED.value,
            origin="auto",
        )
        session.add(group)
        session.flush()
        key_id = max(files, key=stack_key_score).id
        for row in files:
            session.add(
                SimilarityGroupMember(
                    group_id=group.id,
                    source_file_id=row.id,
                    distance=0.0,
                    is_key=row.id == key_id,
                )
            )
            stacked[row.id] = group.id
        changed += 1
    session.flush()
    return changed


def propose_scene_groups(session: Session, project_id: int) -> int:
    """Suggest groups of photos close in time. Keys are chosen later in the dialog."""

    rows = list(
        session.scalars(
            select(SourceFile)
            .where(
                SourceFile.project_id == project_id,
                SourceFile.file_kind == FileKind.PHOTO.value,
                SourceFile.captured_at.is_not(None),
            )
            .order_by(SourceFile.captured_at.asc(), SourceFile.filename.asc())
        )
    )
    overlay = load_cluster_overlay(session, project_id)
    grouped = _source_ids_in_type(session, project_id, ClusterType.GROUP)
    visible = [row for row in rows if not overlay.is_hidden(row.id) and row.id not in grouped]
    created = 0
    cluster: list[SourceFile] = []
    for row in visible:
        if not cluster:
            cluster = [row]
            continue
        last = cluster[-1].captured_at
        current = row.captured_at
        if last is not None and current is not None and current - last <= SCENE_WINDOW:
            cluster.append(row)
            continue
        created += _store_suggested_group(session, project_id, cluster)
        cluster = [row]
    created += _store_suggested_group(session, project_id, cluster)
    session.flush()
    return created


def set_stack_key(session: Session, cluster_id: int, source_file_id: int) -> None:
    group = _require_cluster(session, cluster_id, ClusterType.STACK)
    ids = {item.source_file_id for item in group.members}
    if source_file_id not in ids:
        raise ProjectError("Das Medium gehört nicht zu diesem Stapel.")
    for member in group.members:
        member.is_key = member.source_file_id == source_file_id
    group.origin = "manual"
    group.status = ClusterStatus.ACCEPTED.value
    session.flush()


def create_manual_group(session: Session, project_id: int, source_file_ids: list[int]) -> int:
    """Make the chosen photos one group. Keys stay unset until the inspector."""

    wanted = list(dict.fromkeys(source_file_ids))
    if len(wanted) < 2:
        raise ProjectError("Bitte mindestens zwei Fotos auswählen.")
    rows = list(
        session.scalars(
            select(SourceFile).where(SourceFile.project_id == project_id, SourceFile.id.in_(wanted))
        )
    )
    by_id = {row.id: row for row in rows}
    if any(item_id not in by_id for item_id in wanted):
        raise ProjectError("Ein gewähltes Medium gehört nicht zu diesem Projekt.")
    photos = [by_id[item_id] for item_id in wanted if by_id[item_id].file_kind == FileKind.PHOTO.value]
    if len(photos) < 2:
        raise ProjectError("Bitte mindestens zwei Fotos auswählen.")
    photo_ids = [row.id for row in photos]
    existing = _source_ids_in_type(session, project_id, ClusterType.GROUP)
    group_ids = {existing[item_id] for item_id in photo_ids if item_id in existing}
    if len(group_ids) == 1:
        only_id = next(iter(group_ids))
        group = session.get(SimilarityGroup, only_id)
        if group is not None and {item.source_file_id for item in group.members} == set(photo_ids):
            set_group_keys(session, only_id, [])
            return only_id
    _remove_from_groups(session, project_id, set(photo_ids))
    group = SimilarityGroup(
        project_id=project_id,
        kind=SimilarityKind.VISUAL.value,
        method=SimilarityMethod.MANUAL.value,
        cluster_type=ClusterType.GROUP.value,
        status=ClusterStatus.SUGGESTED.value,
        origin="manual",
    )
    session.add(group)
    session.flush()
    for row in photos:
        session.add(
            SimilarityGroupMember(
                group_id=group.id,
                source_file_id=row.id,
                distance=None,
                is_key=False,
            )
        )
    session.flush()
    return group.id


def set_group_keys(session: Session, cluster_id: int, source_file_ids: list[int]) -> None:
    group = _require_cluster(session, cluster_id, ClusterType.GROUP)
    wanted = list(dict.fromkeys(source_file_ids))
    ids = {item.source_file_id for item in group.members}
    if any(item_id not in ids for item_id in wanted):
        raise ProjectError("Ein gewähltes Foto gehört nicht zu dieser Gruppe.")
    keys = set(wanted)
    for member in group.members:
        member.is_key = member.source_file_id in keys
    group.status = ClusterStatus.ACCEPTED.value if keys else ClusterStatus.SUGGESTED.value
    group.origin = "manual"
    session.flush()


def dismiss_cluster(session: Session, cluster_id: int) -> None:
    group = session.get(SimilarityGroup, cluster_id)
    if group is None:
        raise ProjectError("Stapel oder Gruppe wurde nicht gefunden.")
    group.status = ClusterStatus.DISMISSED.value
    group.origin = "manual"
    session.flush()


def dissolve_group(session: Session, cluster_id: int) -> None:
    group = _require_cluster(session, cluster_id, ClusterType.GROUP)
    session.delete(group)
    session.flush()


def _require_cluster(session: Session, cluster_id: int, expected: ClusterType) -> SimilarityGroup:
    group = session.get(SimilarityGroup, cluster_id)
    if group is None or group.cluster_type != expected:
        label = "Stapel" if expected == ClusterType.STACK else "Gruppe"
        raise ProjectError(f"{label} wurde nicht gefunden.")
    return group


def _source_ids_in_type(session: Session, project_id: int, cluster_type: ClusterType) -> dict[int, int]:
    found: dict[int, int] = {}
    groups = list(
        session.scalars(
            select(SimilarityGroup).where(
                SimilarityGroup.project_id == project_id,
                SimilarityGroup.cluster_type == cluster_type.value,
                SimilarityGroup.status != ClusterStatus.DISMISSED.value,
            )
        )
    )
    for group in groups:
        for member in group.members:
            found[member.source_file_id] = group.id
    return found


def _remove_from_groups(session: Session, project_id: int, source_ids: set[int]) -> None:
    groups = list(
        session.scalars(
            select(SimilarityGroup).where(
                SimilarityGroup.project_id == project_id,
                SimilarityGroup.cluster_type == ClusterType.GROUP.value,
                SimilarityGroup.status != ClusterStatus.DISMISSED.value,
            )
        )
    )
    for group in groups:
        members = list(group.members)
        remaining = [item for item in members if item.source_file_id not in source_ids]
        if len(remaining) == len(members):
            continue
        if len(remaining) < 2:
            session.delete(group)
            continue
        for member in members:
            if member.source_file_id in source_ids:
                session.delete(member)
        if group.status == ClusterStatus.ACCEPTED.value and not any(item.is_key for item in remaining):
            group.status = ClusterStatus.SUGGESTED.value
    session.flush()


def _add_missing_stack_members(session: Session, group_id: int, files: list[SourceFile]) -> bool:
    group = session.get(SimilarityGroup, group_id)
    if group is None:
        return False
    have = {item.source_file_id for item in group.members}
    added = False
    for row in files:
        if row.id in have:
            continue
        session.add(
            SimilarityGroupMember(
                group_id=group.id,
                source_file_id=row.id,
                distance=0.0,
                is_key=False,
            )
        )
        added = True
    if added:
        session.flush()
    if added and group.origin == "auto":
        key = max(files, key=stack_key_score)
        for member in group.members:
            member.is_key = member.source_file_id == key.id
    return added


def _store_suggested_group(session: Session, project_id: int, files: list[SourceFile]) -> int:
    if len(files) < 2:
        return 0
    group = SimilarityGroup(
        project_id=project_id,
        kind=SimilarityKind.VISUAL.value,
        method=SimilarityMethod.PHASH.value,
        cluster_type=ClusterType.GROUP.value,
        status=ClusterStatus.SUGGESTED.value,
        origin="auto",
    )
    session.add(group)
    session.flush()
    for row in files:
        session.add(
            SimilarityGroupMember(
                group_id=group.id,
                source_file_id=row.id,
                distance=None,
                is_key=False,
            )
        )
    return 1


def compute_media_stats(session: Session, project_id: int) -> MediaStats:
    """Project-wide media counts. Hidden cluster members stay in the index."""

    overlay = load_cluster_overlay(session, project_id)
    rows = session.execute(
        select(SourceFile.id, SourceFile.parked, Photo.sort_status)
        .outerjoin(Photo, Photo.source_file_id == SourceFile.id)
        .where(SourceFile.project_id == project_id, SourceFile.file_kind.in_(_STAT_KINDS))
    ).all()
    imported = 0
    gallery = 0
    rejected = 0
    pool = 0
    for source_id, parked, status in rows:
        imported += 1
        is_rejected = status == _REJECTED
        if is_rejected:
            rejected += 1
        if parked:
            pool += 1
        elif not is_rejected and not overlay.is_hidden(source_id):
            gallery += 1
    stacks = 0
    stack_hidden = 0
    groups = 0
    for group in session.scalars(select(SimilarityGroup).where(SimilarityGroup.project_id == project_id)):
        if group.cluster_type == ClusterType.STACK and group.status == ClusterStatus.ACCEPTED:
            stacks += 1
            stack_hidden += sum(1 for member in group.members if not member.is_key)
            continue
        if group.cluster_type == ClusterType.GROUP and group.status != ClusterStatus.DISMISSED:
            groups += 1
    return MediaStats(
        imported=imported,
        gallery=gallery,
        rejected=rejected,
        pool=pool,
        stacks=stacks,
        stack_hidden=stack_hidden,
        groups=groups,
        hidden=len(overlay.hidden),
    )
