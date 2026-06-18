import random
import re
from dataclasses import dataclass

from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.platform.message_type import MessageType


@dataclass
class RollResult:
    expression: str
    total: int
    details: list[str]


@register("astrbot_plugin_miodice", "RuinsFeather", "运行于 AstrBot 的基础 TRPG 骰子插件", "0.1.0")
class MioDicePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.regex(r"^\s*\.(r|roll|投掷|检定)(\s+.*)?$", priority=10)
    async def roll(self, event: AstrMessageEvent):
        """Roll dice and optionally perform a percentile skill check.

        Args:
            event: AstrBot message event.
        """
        text = event.get_message_str().strip()
        args = re.sub(r"^\.(?:r|roll|投掷|检定)\s*", "", text, count=1).strip()
        if not args:
            yield event.plain_result("用法：.r 1d100 侦查60")
            event.stop_event()
            return

        match = re.match(r"^(\d*d\d+(?:[+-]\d*d?\d+)*)\s*(.*)$", args, re.IGNORECASE)
        if not match:
            yield event.plain_result("骰子表达式格式错误，例如：1d100、2d6+3")
            event.stop_event()
            return

        try:
            roll_result = self._roll_expression(match.group(1))
        except ValueError as exc:
            yield event.plain_result(str(exc))
            event.stop_event()
            return

        check_text = match.group(2).strip()
        skill_match = re.match(r"^(.+?)(\d{1,3})$", check_text) if check_text else None
        if skill_match and roll_result.expression.lower() in {"1d100", "d100"}:
            skill_name = skill_match.group(1).strip() or "检定"
            target = int(skill_match.group(2))
            level_name, _level_value = self._coc_success_level(roll_result.total, target)
            yield event.plain_result(
                f"🎲 {skill_name} {target}\n"
                f"投掷：{roll_result.expression} = {roll_result.total}\n"
                f"结果：{level_name}"
            )
        else:
            detail = " + ".join(roll_result.details)
            yield event.plain_result(f"🎲 {roll_result.expression} = {roll_result.total}\n明细：{detail}")
        event.stop_event()

    @filter.regex(r"^\s*\.(vs|战斗)(\s+.*)?$", priority=10)
    async def versus(self, event: AstrMessageEvent):
        """Resolve a two-sided percentile contest.

        Args:
            event: AstrBot message event.
        """
        text = event.get_message_str().strip()
        args = re.sub(r"^\.(?:vs|战斗)\s*", "", text, count=1).strip()
        matches = re.findall(r"([^\s\d]+)\s*(\d{1,3})", args)
        if len(matches) < 2:
            yield event.plain_result("用法：.vs 攻击55 闪避40")
            event.stop_event()
            return

        left_name, left_target_text = matches[0]
        right_name, right_target_text = matches[1]
        left_target = int(left_target_text)
        right_target = int(right_target_text)
        left_roll = random.randint(1, 100)
        right_roll = random.randint(1, 100)
        left_level_name, left_level = self._coc_success_level(left_roll, left_target)
        right_level_name, right_level = self._coc_success_level(right_roll, right_target)

        if left_level != right_level:
            winner = left_name if left_level > right_level else right_name
            reason = "成功等级更高"
        elif left_roll != right_roll:
            winner = left_name if left_roll > right_roll else right_name
            reason = "成功等级相同，原始点数更高"
        else:
            winner = "平局"
            reason = "成功等级与原始点数均相同"

        yield event.plain_result(
            f"⚔️ 对抗检定\n"
            f"{left_name}{left_target}：1d100 = {left_roll}（{left_level_name}）\n"
            f"{right_name}{right_target}：1d100 = {right_roll}（{right_level_name}）\n"
            f"判定：{winner}（{reason}）"
        )
        event.stop_event()

    @filter.regex(r"^\s*\.(dmg|伤害)(\s+.*)?$", priority=10)
    async def damage(self, event: AstrMessageEvent):
        """Calculate damage after bonus and armor.

        Args:
            event: AstrBot message event.
        """
        text = event.get_message_str().strip()
        args = re.sub(r"^\.(?:dmg|伤害)\s*", "", text, count=1).strip()
        match = re.match(r"^(\d*d\d+(?:[+-]\d*d?\d+)*)\s*(.*)$", args, re.IGNORECASE)
        if not match:
            yield event.plain_result("用法：.dmg 1d10+2 伤害加成1 护甲2 hp12")
            event.stop_event()
            return

        try:
            weapon = self._roll_expression(match.group(1))
        except ValueError as exc:
            yield event.plain_result(str(exc))
            event.stop_event()
            return

        tail = match.group(2)
        bonus_match = re.search(r"(?:伤害加成|db|加成)\s*([+-]?\d+)", tail, re.IGNORECASE)
        armor_match = re.search(r"(?:护甲|armor|armour)\s*([+-]?\d+)", tail, re.IGNORECASE)
        hp_match = re.search(r"hp\s*([+-]?\d+)", tail, re.IGNORECASE)
        bonus = int(bonus_match.group(1)) if bonus_match else 0
        armor = int(armor_match.group(1)) if armor_match else 0
        hp = int(hp_match.group(1)) if hp_match else 0
        final_damage = max(0, weapon.total + bonus - armor)
        parts = [f"武器伤害 {weapon.expression} = {weapon.total}"]
        if bonus:
            parts.append(f"伤害加成 {bonus:+d}")
        if armor:
            parts.append(f"护甲 -{armor}")
        if hp > 0:
            remaining_hp = hp - final_damage
            parts.append(f"剩余 HP：{remaining_hp}/{hp}")
            if final_damage * 2 >= hp:
                parts.append("触发重伤阈值：需进行体质检定，失败则昏迷并失去行动能力")
            else:
                parts.append("未触发重伤阈值")
            if remaining_hp <= -10:
                parts.append("生命状态：死亡")
            elif remaining_hp <= 0:
                parts.append("生命状态：濒死")

        yield event.plain_result(f"🩸 伤害结算：{final_damage}\n" + "\n".join(parts))
        event.stop_event()

    @filter.regex(r"^\s*\.(rh|暗投)(\s+.*)?$", priority=10)
    async def hidden_roll(self, event: AstrMessageEvent):
        """Perform a private keeper roll.

        Args:
            event: AstrBot message event.
        """
        text = event.get_message_str().strip()
        args = re.sub(r"^\.(?:rh|暗投)\s*", "", text, count=1).strip() or "1d100"
        try:
            roll_result = self._roll_expression(args)
        except ValueError as exc:
            yield event.plain_result(str(exc))
            event.stop_event()
            return

        private_result = f"🎲 KP暗骰：{roll_result.expression} = {roll_result.total}\n明细：{' + '.join(roll_result.details)}"
        if event.get_message_type() == MessageType.FRIEND_MESSAGE:
            yield event.plain_result(private_result)
        else:
            sender_id = event.get_sender_id()
            if sender_id:
                private_umo = f"{event.get_platform_id()}:{MessageType.FRIEND_MESSAGE.value}:{sender_id}"
                await self.context.send_message(private_umo, MessageChain().message(private_result))
            yield event.plain_result("KP进行了暗骰。")
        event.stop_event()

    @filter.regex(r"^\s*\.(st|状态)(\s+.*)?$", priority=10)
    async def status(self, event: AstrMessageEvent):
        """View or update a character status sheet.

        Args:
            event: AstrBot message event.
        """
        text = event.get_message_str().strip()
        args = re.sub(r"^\.(?:st|状态)\s*", "", text, count=1).strip()
        if not args:
            yield event.plain_result("用法：.st 林默 或 .st 林默 HP 10 中毒")
            event.stop_event()
            return

        tokens = args.split()
        name = tokens[0]
        updates = tokens[1:]
        store_key = f"characters:{event.unified_msg_origin}"
        characters = await self.get_kv_data(store_key, {})
        character = characters.get(name, {"HP": None, "MP": None, "status": []})

        if updates:
            index = 0
            while index < len(updates):
                key = updates[index].upper()
                if key in {"HP", "MP"} and index + 1 < len(updates) and re.fullmatch(r"[+-]?\d+", updates[index + 1]):
                    value = int(updates[index + 1])
                    character[key] = value
                    index += 2
                    continue
                raw_status = updates[index]
                remove = raw_status.startswith("-")
                status_name = raw_status[1:] if remove else raw_status
                if status_name:
                    current_status = character.setdefault("status", [])
                    if remove:
                        character["status"] = [item for item in current_status if item != status_name]
                    elif status_name not in current_status:
                        current_status.append(status_name)
                index += 1
            characters[name] = character
            await self.put_kv_data(store_key, characters)

        hp_text = character.get("HP") if character.get("HP") is not None else "未记录"
        mp_text = character.get("MP") if character.get("MP") is not None else "未记录"
        status_text = "、".join(character.get("status", [])) or "无"
        prefix = "已更新角色状态" if updates else "角色状态"
        yield event.plain_result(f"📋 {prefix}：{name}\nHP：{hp_text}\nMP：{mp_text}\n状态：{status_text}")
        event.stop_event()

    def _roll_expression(self, expression: str) -> RollResult:
        """Roll a limited dice expression.

        Args:
            expression: Dice expression like 1d100 or 2d6+3.

        Returns:
            RollResult containing total and detail strings.

        Raises:
            ValueError: If the expression is invalid or too large.
        """
        normalized = expression.replace(" ", "").lower()
        if not re.fullmatch(r"[+-]?\d*d\d+(?:[+-]\d*d?\d+)*", normalized):
            raise ValueError("骰子表达式格式错误，例如：1d100、2d6+3")

        total = 0
        details = []
        for sign, term in re.findall(r"([+-]?)(\d*d?\d+)", normalized):
            factor = -1 if sign == "-" else 1
            if "d" in term:
                count_text, sides_text = term.split("d", 1)
                count = int(count_text or "1")
                sides = int(sides_text)
                if count < 1 or count > 100 or sides < 2 or sides > 100000:
                    raise ValueError("骰子数量需为 1-100，面数需为 2-100000。")
                rolls = [random.randint(1, sides) for _ in range(count)]
                subtotal = sum(rolls) * factor
                total += subtotal
                signed = "-" if factor < 0 else ""
                details.append(f"{signed}{count}d{sides}{rolls}")
            else:
                value = int(term) * factor
                total += value
                details.append(f"{value:+d}")
        return RollResult(normalized, total, details)

    def _coc_success_level(self, roll: int, target: int) -> tuple[str, int]:
        """Calculate a COC-like percentile success level.

        Args:
            roll: D100 raw roll.
            target: Skill target value.

        Returns:
            A tuple of display name and comparable numeric level.
        """
        if roll == 1:
            return "大成功", 4
        if roll >= 99:
            return "大失败", -1
        if roll > target:
            return "失败", 0
        if roll <= target // 5:
            return "极难成功", 3
        if roll <= target // 2:
            return "困难成功", 2
        return "成功", 1
