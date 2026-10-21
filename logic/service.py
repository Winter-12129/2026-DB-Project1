from decimal import Decimal, InvalidOperation

from common.errors import ConflictError, NotFoundError, ValidationError
from common.ids import generate_rule_id
from common.time_utils import utc_now
from questions import service as question_service
from surveys import repository as survey_repository
from surveys import service as survey_service


def _ensure_draft(document):
    if document.get("status") != "draft":
        raise ConflictError("只有草稿问卷可以修改跳转规则")


def _ordered_questions(document):
    return sorted(
        document.get("questions", []),
        key=lambda question: question.get("order", 0),
    )


def _question_map(document):
    return {
        question["id"]: question
        for question in document.get("questions", [])
    }


def _as_decimal(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValidationError("跳转条件中的数字格式不正确") from exc
    if not number.is_finite():
        raise ValidationError("跳转条件中的数字必须有限")
    return number


def _number_value(value):
    number = _as_decimal(value)
    return int(number) if number == number.to_integral_value() else float(number)


def _option_values(question, option_ids):
    valid_ids = {option["id"] for option in question.get("options", [])}
    values = list(dict.fromkeys(option_ids))
    if not values:
        raise ValidationError("请至少选择一个触发选项")
    if any(value not in valid_ids for value in values):
        raise ValidationError("跳转规则包含无效选项")
    return values


def add_rule(survey_id, owner_id, question_id, form):
    document = survey_service.get_owned_survey_doc(survey_id, owner_id)
    _ensure_draft(document)

    source = question_service.get_question(document, question_id)
    if source is None:
        raise NotFoundError("题目不存在")

    target_id = (form.get("target_question_id") or "").strip()
    if target_id != "END":
        target = question_service.get_question(document, target_id)
        if target is None:
            raise ValidationError("跳转目标题不存在")
        if target.get("order", 0) <= source.get("order", 0):
            raise ValidationError("只能跳转到当前题目之后的题目")
        action = {"type": "jump", "targetQuestionId": target_id}
    else:
        action = {"type": "end"}

    try:
        priority = int(form.get("priority") or 10)
    except ValueError as exc:
        raise ValidationError("优先级必须是整数") from exc
    if priority < 1:
        raise ValidationError("优先级必须大于 0")

    for existing in document.get("rules", []):
        if (
            existing.get("fromQuestionId") == question_id
            and existing.get("priority") == priority
        ):
            raise ValidationError("同一道题不能使用重复的优先级")

    question_type = source.get("type")
    if question_type == "single_choice":
        option_id = form.get("option_id")
        _option_values(source, [option_id] if option_id else [])
        clause = {
            "questionId": question_id,
            "operator": "eq",
            "value": option_id,
        }
    elif question_type == "multiple_choice":
        values = _option_values(
            source,
            form.getlist("option_ids"),
        )
        match = form.get("match") or "any"
        if match not in {"any", "all"}:
            raise ValidationError("多选匹配方式无效")
        clause = {
            "questionId": question_id,
            "operator": "includes_any" if match == "any" else "includes_all",
            "values": values,
        }
    elif question_type == "number":
        operator = form.get("operator") or "eq"
        if operator not in {"eq", "gt", "gte", "lt", "lte", "between"}:
            raise ValidationError("数字比较方式无效")
        if operator == "between":
            minimum = _number_value(form.get("min_value"))
            maximum = _number_value(form.get("max_value"))
            if maximum < minimum:
                raise ValidationError("数字范围的最大值不能小于最小值")
            clause = {
                "questionId": question_id,
                "operator": "between",
                "min": minimum,
                "max": maximum,
            }
        else:
            value = _number_value(form.get("value"))
            clause = {
                "questionId": question_id,
                "operator": operator,
                "value": value,
            }
    else:
        raise ValidationError("文本题暂不支持跳转条件")

    rule = {
        "id": generate_rule_id(),
        "fromQuestionId": question_id,
        "priority": priority,
        "when": {
            "match": "all",
            "clauses": [clause],
        },
        "action": action,
    }
    rules = list(document.get("rules", []))
    rules.append(rule)
    survey_repository.update_fields(
        document["_id"],
        {"rules": rules, "updatedAt": utc_now()},
    )
    return rule


def delete_rule(survey_id, owner_id, rule_id):
    document = survey_service.get_owned_survey_doc(survey_id, owner_id)
    _ensure_draft(document)
    rules = list(document.get("rules", []))
    remaining = [rule for rule in rules if rule.get("id") != rule_id]
    if len(remaining) == len(rules):
        raise NotFoundError("跳转规则不存在")
    survey_repository.update_fields(
        document["_id"],
        {"rules": remaining, "updatedAt": utc_now()},
    )


def _clause_matches(clause, answers):
    answer = answers.get(clause.get("questionId"))
    if answer is None or answer == "" or answer == []:
        return False

    operator = clause.get("operator")
    if operator == "eq":
        expected = clause.get("value")
        if isinstance(expected, (int, float)):
            return _as_decimal(answer) == _as_decimal(expected)
        return str(answer) == str(expected)
    if operator == "in":
        return answer in clause.get("values", [])
    if operator == "includes_any":
        values = clause.get("values", [])
        return isinstance(answer, list) and any(value in answer for value in values)
    if operator == "includes_all":
        values = clause.get("values", [])
        return isinstance(answer, list) and all(value in answer for value in values)
    if operator == "not_includes":
        values = clause.get("values", [])
        return isinstance(answer, list) and all(value not in answer for value in values)
    if operator in {"gt", "gte", "lt", "lte", "between"}:
        actual = _as_decimal(answer)
        if operator == "between":
            return (
                _as_decimal(clause["min"])
                <= actual
                <= _as_decimal(clause["max"])
            )
        expected = _as_decimal(clause["value"])
        return {
            "gt": actual > expected,
            "gte": actual >= expected,
            "lt": actual < expected,
            "lte": actual <= expected,
        }[operator]
    if operator == "integer":
        actual = _as_decimal(answer)
        return actual == actual.to_integral_value()
    return False


def rule_matches(rule, answers):
    clauses = rule.get("when", {}).get("clauses", [])
    if not clauses:
        return False
    results = [
        _clause_matches(clause, answers)
        for clause in clauses
    ]
    if rule.get("when", {}).get("match") == "any":
        return any(results)
    return all(results)


def next_step(document, current_question_id, answers):
    rules = sorted(
        [
            rule
            for rule in document.get("rules", [])
            if rule.get("fromQuestionId") == current_question_id
        ],
        key=lambda rule: (rule.get("priority", 0), rule.get("id", "")),
    )
    for rule in rules:
        if rule_matches(rule, answers):
            action = rule.get("action", {})
            if action.get("type") == "end":
                return "END"
            if action.get("type") == "jump":
                return action.get("targetQuestionId")

    questions = _ordered_questions(document)
    for index, question in enumerate(questions):
        if question.get("id") == current_question_id:
            if index + 1 < len(questions):
                return questions[index + 1]["id"]
            return "END"
    return "END"


def replay_path(document, answers):
    if not isinstance(answers, dict):
        raise ValidationError("答案格式必须是一个对象")

    questions = _ordered_questions(document)
    if not questions:
        raise ValidationError("问卷还没有题目")

    by_id = {question["id"]: question for question in questions}
    current = document.get("startQuestionId") or questions[0]["id"]
    visited = []
    normalized_answers = []
    guard = 0

    while current != "END":
        guard += 1
        if guard > len(questions) + 1:
            raise ValidationError("问卷跳转出现了循环")
        if current in visited:
            raise ValidationError("问卷跳转出现了循环")
        question = by_id.get(current)
        if question is None:
            raise ValidationError("问卷跳转目标不存在")

        raw_value = answers.get(current)
        value = question_service.validate_answer(question, raw_value)
        visited.append(current)
        if value is not None:
            normalized_answers.append(
                {
                    "questionId": current,
                    "type": question["type"],
                    "value": value,
                }
            )
        current = next_step(document, current, answers)

    return visited, normalized_answers


def _option_label(question, option_id):
    for option in question.get("options", []):
        if option.get("id") == option_id:
            return option.get("label", option_id)
    return option_id


def _target_label(document, action):
    if action.get("type") == "end":
        return "结束问卷"
    target_id = action.get("targetQuestionId")
    target = question_service.get_question(document, target_id)
    if target is None:
        return "未知题目"
    return f"第 {target.get('order', '?')} 题"


def rule_views(document):
    questions = _question_map(document)
    views = []
    for rule in sorted(
        document.get("rules", []),
        key=lambda item: (item.get("priority", 0), item.get("id", "")),
    ):
        source = questions.get(rule.get("fromQuestionId"))
        if source is None:
            description = "规则引用的题目已不存在"
        else:
            clauses = rule.get("when", {}).get("clauses", [])
            if not clauses:
                description = "规则缺少条件"
                views.append(
                    {
                        "id": rule.get("id"),
                        "sourceQuestionId": rule.get("fromQuestionId"),
                        "priority": rule.get("priority", 0),
                        "description": description,
                        "rule": rule,
                    }
                )
                continue
            clause = clauses[0]
            operator = clause.get("operator")
            if operator == "eq":
                condition = f"选择“{_option_label(source, clause.get('value'))}”"
            elif operator in {"includes_any", "includes_all"}:
                labels = [
                    _option_label(source, value)
                    for value in clause.get("values", [])
                ]
                word = "任意" if operator == "includes_any" else "全部"
                condition = f"包含{word}：{' / '.join(labels)}"
            elif operator == "between":
                condition = f"{clause.get('min')} ≤ 数值 ≤ {clause.get('max')}"
            else:
                symbols = {
                    "eq": "=",
                    "gt": ">",
                    "gte": "≥",
                    "lt": "<",
                    "lte": "≤",
                }
                condition = f"数值 {symbols.get(operator, operator)} {clause.get('value')}"
            description = (
                f"第 {source.get('order', '?')} 题：{condition}"
                f" → {_target_label(document, rule.get('action', {}))}"
            )
        views.append(
            {
                "id": rule.get("id"),
                "sourceQuestionId": rule.get("fromQuestionId"),
                "priority": rule.get("priority", 0),
                "description": description,
                "rule": rule,
            }
        )
    return views


def public_rules(document):
    return [
        {
            "id": rule.get("id"),
            "fromQuestionId": rule.get("fromQuestionId"),
            "priority": rule.get("priority", 0),
            "when": rule.get("when", {}),
            "action": rule.get("action", {}),
        }
        for rule in document.get("rules", [])
    ]


def validate_rules_for_publish(document):
    questions = _question_map(document)
    priorities = set()
    rule_ids = set()
    for rule in document.get("rules", []):
        rule_id = rule.get("id")
        if not rule_id or rule_id in rule_ids:
            raise ValidationError("跳转规则 ID 缺失或重复")
        rule_ids.add(rule_id)

        source = questions.get(rule.get("fromQuestionId"))
        if source is None:
            raise ValidationError("跳转规则引用的来源题不存在")
        key = (source["id"], rule.get("priority", 0))
        if key in priorities:
            raise ValidationError("同一道题存在重复的规则优先级")
        priorities.add(key)

        action = rule.get("action", {})
        if action.get("type") == "jump":
            target = questions.get(action.get("targetQuestionId"))
            if target is None:
                raise ValidationError("跳转目标题不存在")
            if target.get("order", 0) <= source.get("order", 0):
                raise ValidationError("跳转目标必须排在来源题之后")
        elif action.get("type") != "end":
            raise ValidationError("存在未知的跳转动作")

        clauses = rule.get("when", {}).get("clauses", [])
        if not clauses:
            raise ValidationError("跳转规则缺少条件")
        for clause in clauses:
            question = questions.get(clause.get("questionId"))
            if question is None:
                raise ValidationError("跳转条件引用的题目不存在")
            if question.get("order", 0) > source.get("order", 0):
                raise ValidationError("跳转条件不能引用尚未回答的题目")
            operator = clause.get("operator")
            question_type = question.get("type")
            if question_type == "single_choice" and operator != "eq":
                raise ValidationError("单选题跳转条件操作符无效")
            if question_type == "multiple_choice" and operator not in {
                "includes_any",
                "includes_all",
                "not_includes",
            }:
                raise ValidationError("多选题跳转条件操作符无效")
            if question_type == "number" and operator not in {
                "eq",
                "gt",
                "gte",
                "lt",
                "lte",
                "between",
                "integer",
            }:
                raise ValidationError("数字题跳转条件操作符无效")
            if question_type == "text":
                raise ValidationError("文本题暂不支持跳转条件")

            if question_type == "single_choice":
                option_ids = {
                    option["id"]
                    for option in question.get("options", [])
                }
                if clause.get("value") not in option_ids:
                    raise ValidationError("单选题跳转条件引用了无效选项")
            if question_type == "multiple_choice":
                option_ids = {
                    option["id"]
                    for option in question.get("options", [])
                }
                values = clause.get("values", [])
                if not values or any(value not in option_ids for value in values):
                    raise ValidationError("多选题跳转条件引用了无效选项")
            if question_type == "number":
                if operator == "between":
                    minimum = _as_decimal(clause.get("min"))
                    maximum = _as_decimal(clause.get("max"))
                    if maximum < minimum:
                        raise ValidationError("数字跳转范围无效")
                else:
                    _as_decimal(clause.get("value"))
