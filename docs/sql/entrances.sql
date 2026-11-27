-- 출입구 등록 웹앱(web/entrance)용 테이블과 사진 저장소.
-- Supabase 대시보드 > SQL Editor에서 한 번 실행한다.
--
-- 웹앱은 공개 키(sb_publishable_...)로 접속한다. 아래 정책은 공개 키로
-- 등록(INSERT)과 조회(SELECT)만 허용하고, 수정·삭제는 막는다.
-- 링크를 아는 사람은 누구나 등록할 수 있으므로 링크는 팀 안에서만 공유한다.

create table if not exists public.entrances (
    id               uuid primary key,             -- 웹앱이 만든 ID. 재전송해도 한 번만 저장된다
    created_at       timestamptz not null default now(),
    recorded_at      timestamptz not null,         -- 휴대폰에서 저장 버튼을 누른 시각
    recorder         text,

    building_id      text,                         -- web/entrance/buildings.json의 id (목록 밖이면 null)
    building_name    text not null,
    entrance_name    text,

    -- 사용자가 조정한 실제 문 위치
    pin_lat          double precision not null check (pin_lat between -90 and 90),
    pin_lon          double precision not null check (pin_lon between -180 and 180),
    -- 조정 전 GPS 원래 위치 (없을 수 있음)
    gps_lat          double precision,
    gps_lon          double precision,
    gps_accuracy_m   double precision check (gps_accuracy_m is null or gps_accuracy_m >= 0),
    gps_time         timestamptz,
    pin_moved_m      double precision,             -- GPS 위치에서 핀을 옮긴 거리

    -- 상태: yes / no / unknown
    stairs           text not null default 'unknown' check (stairs in ('yes', 'no', 'unknown')),
    stairs_count     integer check (stairs_count is null or stairs_count >= 0),
    ramp             text not null default 'unknown' check (ramp in ('yes', 'no', 'unknown')),
    threshold        text not null default 'unknown' check (threshold in ('yes', 'no', 'unknown')),
    threshold_cm     double precision check (threshold_cm is null or threshold_cm >= 0),
    door_type        text not null default 'unknown'
                     check (door_type in ('automatic', 'button', 'push', 'pull', 'revolving', 'open', 'unknown')),

    opening_hours    text,                         -- 자유 메모. 확정 일정은 data/campus/schedule.json
    note             text,
    photo_path       text,                         -- Storage 버킷 entrance-photos 안 경로
    client           text                          -- 브라우저 정보 (문제 추적용)
);

alter table public.entrances enable row level security;

grant select, insert on public.entrances to anon, authenticated;
grant select, insert, update, delete on public.entrances to service_role;

drop policy if exists "entrances read" on public.entrances;
create policy "entrances read" on public.entrances
    for select to anon, authenticated using (true);

drop policy if exists "entrances insert" on public.entrances;
create policy "entrances insert" on public.entrances
    for insert to anon, authenticated with check (true);

-- 사진 저장소. public = true라서 사진 URL로 바로 볼 수 있다.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('entrance-photos', 'entrance-photos', true, 5242880, array['image/jpeg'])
on conflict (id) do nothing;

drop policy if exists "entrance photos insert" on storage.objects;
create policy "entrance photos insert" on storage.objects
    for insert to anon, authenticated with check (bucket_id = 'entrance-photos');

drop policy if exists "entrance photos read" on storage.objects;
create policy "entrance photos read" on storage.objects
    for select to anon, authenticated using (bucket_id = 'entrance-photos');
