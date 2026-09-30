"""Read-only recovery of persisted selections; never a renewed write grant."""
from modagent.config import make_game_instance_id
from . import store


class RecoveryRejected(ValueError):
    pass


def preview_recovery(task_id, cfg):
    task = store.get_task(task_id)
    if not task:
        raise RecoveryRejected('task_not_found')
    spec = task.get('spec') or {}
    constraints = spec.get('constraints') or {}
    instance = constraints.get('game_instance_id')
    if not instance:
        raise RecoveryRejected('legacy_plan_revalidation_required')
    if instance != make_game_instance_id(getattr(cfg, 'game_root', '')):
        raise RecoveryRejected('game_instance_changed')
    targets = spec.get('targets') or []
    if not targets or not all(isinstance(row, dict) and row.get('source') for row in targets):
        raise RecoveryRejected('selection_checkpoint_missing')
    if task.get('state') == 'COMPLETED':
        raise RecoveryRejected('task_already_completed')
    return {
        'ok': True,
        'action': 'rebuild_plan',
        'recovery_task_id': task_id,
        'session_id': spec.get('session_id'),
        'recommendation_selection': targets,
        'selection_action': 'plan',
        'message': '恢复原来选择的 Mod、版本和变体，先重新核验安装计划；不要搜索其他目标，不要下载安装。',
        'original_goal': spec.get('user_goal', ''),
        'previous_outcome': task.get('outcome') or {},
        'write_authorized': False,
        'notice': '已保留原选择；此操作只恢复计划并核验现状，不会重放旧安装。旧副作用记录不能替代文件核验。',
    }
