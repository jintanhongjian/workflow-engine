from django.http import JsonResponse
from datetime import timedelta, datetime
from django.utils import timezone

class ApiResponse:
    """
    统一响应格式：
    {
        "code": 200,          # 业务状态码
        "success": true,      # 快速判断标识
        "message": "描述信息", # 提示文字
        "data": { ... }       # 实际数据载体
    }
    """
    
    @staticmethod
    def success(data=None, message="Success", code=200):
        return JsonResponse({
            'code': code,
            'success': True,
            'message': message,
            'data': data or {}
        }, status=200)

    @staticmethod
    def fail(message="Error", code=400, data=None, status=400):
        return JsonResponse({
            'code': code,
            'success': False,
            'message': message,
            'data': data or {}
        }, status=status)

    @staticmethod
    def unauthorized(message="未授权或登录失效"):
        return ApiResponse.fail(message=message, code=401, status=401)
    
class ScheduleType:
    # 定义周期类型常量和选择项
    plan_type = [
        ('interval', '固定间隔'),
        ('period', '固定周期'),
        ('specdate', '指定日期'),
        ('realtime', '实时')
    ]
    
    Seconds = 'seconds'
    Minutes = 'minutes'
    Hours = 'hours'
    Days = 'days'

    INTERVAL_CHOICES = [
        ('Seconds', '秒'),
        ('Minutes', '分钟'),
        ('Hours', '小时'),
        ('Days', '天'),
    ]

    DAILY = 'daily'
    WEEKLY = 'weekly'
    MONTHLY = 'monthly'
    QUARTERLY = 'quarterly'
    YEARLY = 'yearly'
    REALTIME = 'realtime'   

    PERIOD_CHOICES = [
        ('daily', '每日'),
        ('weekly', '每周'),
        ('monthly', '每月'),
        ('quarterly', '季度'),
        ('yearly', '每年'),
        ('realtime', '实时'),
    ]
    
    # 1. 核心判断逻辑：兼容季度和年度
    @staticmethod
    def should_run_task(plan_type: str ='interval', interval: int = 0, interval_period: str = None, 
                        period: str = None, spec_date: datetime = None, is_recurring: bool = False,
                        last_run_at: datetime = None):
        now = timezone.now()
        
        if not last_run_at:
            return {'should_run': False, 'next_run_at': None}
        if plan_type == 'realtime':
            return {'should_run': True, 'next_run_at': None}
        
        if plan_type == 'specdate' and spec_date:
            should_run = now >= spec_date
            # 组合成下一年的spec_date
            next_spec_date = spec_date.replace(year=spec_date.year + 1)
            next_run_at = next_spec_date if is_recurring else None
            return {'should_run': should_run, 'next_run_at': next_run_at}
        
        if plan_type == 'interval' and interval > 0 and interval_period:           
            if interval_period == 'Seconds':
                should_run = now >= last_run_at + timedelta(seconds=interval)
                next_run_at = last_run_at + timedelta(seconds=interval*2)
            elif interval_period == 'Minutes':
                should_run = now >= last_run_at + timedelta(minutes=interval)
                next_run_at = last_run_at + timedelta(minutes=interval*2)
            elif interval_period == 'Hours':
                should_run = now >= last_run_at + timedelta(hours=interval)
                next_run_at = last_run_at + timedelta(hours=interval*2)
            elif interval_period == 'Days':
                should_run = now >= last_run_at + timedelta(days=interval)
                next_run_at = last_run_at + timedelta(days=interval*2)
            else:
                should_run = False
                next_run_at = None
            return {'should_run': should_run, 'next_run_at': next_run_at}
            
        if plan_type == 'period' and period:    
            if period == 'daily':
                should_run = now >= last_run_at + timedelta(days=1)
                next_run_at = last_run_at + timedelta(days=2)
            elif period == 'weekly':
                should_run = now >= last_run_at + timedelta(weeks=1)
                next_run_at = last_run_at + timedelta(weeks=2)
            elif period == 'monthly':
                should_run = now >= last_run_at.replace(month=last_run_at.month % 12 + 1) # 简单处理月末问题
                next_run_at = last_run_at.replace(month=(last_run_at.month + 1) % 12 or 12)
            elif period == 'quarterly':
                should_run = now >= last_run_at.replace(month=((last_run_at.month - 1) // 3 + 1) * 3 % 12 + 1) # 简单处理季度末问题
                next_run_at = last_run_at.replace(month=((last_run_at.month - 1) // 3 + 2) * 3 % 12 + 1)
            elif period == 'yearly':
                should_run = now >= last_run_at.replace(year=last_run_at.year + 1)
                next_run_at = last_run_at.replace(year=last_run_at.year + 2)
            else:
                should_run = False
                next_run_at = None
            return {'should_run': should_run, 'next_run_at': next_run_at}

    @staticmethod
    def get_schedule_config(plan_type: str ='interval', interval: int = 0, interval_period: str = None, 
                        period: str = None, spec_date: datetime = None, is_recurring: bool = False) -> dict:
        """
        根据调度策略返回具体的调度配置类型和参数。
        返回格式:
        {
            'type': 'crontab' | 'interval' | 'clocked' | None,
            'params': { ... } # 对应 Schedule 模型的字段参数
        }
        """
        
        # 1. Realtime (实时任务，不通过定时调度)
        if plan_type == 'realtime':
            return {'type': None, 'params': {}}

        # 2. Spec Date (指定日期)
        if plan_type == 'specdate' and spec_date:
            if is_recurring:
                # 每年重复 -> 使用 Crontab
                return {
                    'type': 'crontab',
                    'params': {
                        'minute': str(spec_date.minute),
                        'hour': str(spec_date.hour),
                        'day_of_month': str(spec_date.day),
                        'month_of_year': str(spec_date.month),
                        'day_of_week': '*'
                    }
                }
            else:
                # 单次执行 -> 使用 ClockedSchedule (如果您安装了django-celery-beat并启用了它)
                # 或者有些系统选择忽略或使用一次性任务队列
                # 这里假设我们希望返回 Clocked 配置
                return {
                    'type': 'clocked',
                    'params': {
                        'clocked_time': spec_date
                    }
                }

        # 3. Period (固定周期) -> Crontab
        if plan_type == 'period' and period:
            cron = {
                'minute': '0', 'hour': '0', 'day_of_week': '*', 'day_of_month': '*', 'month_of_year': '*'
            }
            if period == 'daily':
                pass # 0 0 * * *
            elif period == 'weekly':
                cron['day_of_week'] = '1' # Monday
            elif period == 'monthly':
                cron['day_of_month'] = '1'
            elif period == 'quarterly':
                cron['day_of_month'] = '1'
                cron['month_of_year'] = '*/3'
            elif period == 'yearly':
                cron['day_of_month'] = '1'
                cron['month_of_year'] = '1'
            elif period == 'realtime':
                return {'type': None, 'params': {}}
            
            return {'type': 'crontab', 'params': cron}

        # 4. Interval (固定间隔)
        if plan_type == 'interval' and interval > 0 and interval_period:
            # 优先使用 Celery Native Interval Schedule (支持秒级)
            # 只要是标准的间隔，都推荐用 IntervalSchedule，因为它比 Crontab 的 */x 更语义化且准确
            # 除非间隔单位是复杂的（如 crontab 才能表达的逻辑），但在 plan_type='interval' 下通常就是简单间隔
            
            from django_celery_beat.models import IntervalSchedule
            period_map = {
                'seconds': IntervalSchedule.SECONDS,
                'minutes': IntervalSchedule.MINUTES,
                'hours': IntervalSchedule.HOURS,
                'days': IntervalSchedule.DAYS,
                'microseconds': IntervalSchedule.MICROSECONDS
            }
            
            p_key = interval_period.lower()
            if p_key in period_map:
                return {
                    'type': 'interval',
                    'params': {
                        'every': interval,
                        'period': period_map[p_key]
                    }
                }
            
            # 如果是月/年 (IntervalSchedule 不支持)，回退到 Crontab (虽然不太精确)
            defaults = {'minute': '0', 'hour': '0', 'day_of_week': '*', 'day_of_month': '*', 'month_of_year': '*'}
            if p_key == 'months': # 粗略地每月，Crontab 很难精确表达 "每5个月"
                defaults['month_of_year'] = f'*/{interval}'
                defaults['day_of_month'] = '1'
                return {'type': 'crontab', 'params': defaults}
            elif p_key == 'years':
                # 几乎无法用 Crontab 表达 "每 N 年"，视为 Yearly
                defaults['month_of_year'] = '1'
                defaults['day_of_month'] = '1'
                return {'type': 'crontab', 'params': defaults}
                
        # 默认
        return {'type': None, 'params': {}}

    @staticmethod
    def get_default_crontab(plan_type: str ='interval', interval: int = 0, interval_period: str = None, 
                        period: str = None, spec_date: datetime = None, is_recurring: bool = False) -> dict:
        """
        保留此方法以兼容旧代码，但在内部调用 get_schedule_config。
        仅当类型为 crontab 时返回字典，否则返回 None。
        """
        config = ScheduleType.get_schedule_config(plan_type, interval, interval_period, period, spec_date, is_recurring)
        if config['type'] == 'crontab':
            return config['params']
        return None