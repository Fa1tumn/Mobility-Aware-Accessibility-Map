// config.js로 복사해서 쓴다(config.js는 git에 올리지 않는다).
// 공개 키(sb_publishable_...)만 넣는다. 비밀 키(sb_secret_...)는 넣으면 안 된다.
window.ENTRANCE_CONFIG = {
  url: "https://xxxx.supabase.co",
  key: "sb_publishable_...",
  table: "entrances",
  bucket: "entrance-photos",
};
