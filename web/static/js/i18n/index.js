// 英文词表汇总入口：按模块拆分便于维护，这里统一注册到 i18n 引擎。
// 词表 key 一律是源码里的中文原文，因此同一条文案在不同模块重复出现也无害。
import { register } from "../core/i18n.js";

import app from "./en.app.js";
import core from "./en.core.js";
import chat from "./en.chat.js";
import chatpops from "./en.chatpops.js";
import models from "./en.models.js";
import media from "./en.media.js";
import settings from "./en.settings.js";
import fragments from "./en.fragments.js";

for (const f of [app, core, chat, chatpops, models, media, settings, fragments]) {
  register(f);
}