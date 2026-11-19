export type UserRole = 'admin' | 'user'
export interface User { id: number; username: string; display_name: string; role: UserRole; roles?: UserRole[]; is_active: boolean; status: '正常' | '锁定'; must_change_password: boolean }
export interface Category { id: number; name: string }
export type TaskPriority = '高' | '中' | '低'
export interface Task { id: number; board_task_id?: number | null; meeting_task_id?: number | null; meeting_id?: number | null; meeting_date?: string | null; review_issue_id?: number | null; position: number; category_name: string | null; task_group: string; description: string; status: string | null; priority?: TaskPriority | null; transferred_by?: string | null; work_days: number[]; notes: string }
export interface WeekData { revision: number; tasks: Task[]; no_source?: boolean }
export interface ReviewIssue {
  id: number; project_id: number; author: string; author_name: string; mine: boolean; anonymous: boolean
  title: string; severity: string; category: string; dimension: string; sha: string; commit_message: string
  path: string; start_line: number | null; end_line: number | null; existing_code: string
  risk: string; suggestion: string; suggestion_code: string; status: string | null; notes: string
  task_added: boolean; editable: boolean
}
export interface ReportTab { id: number; name: string; is_active: boolean; is_deleted?: boolean }
export type TaskField = Pick<Task, 'category_name' | 'task_group' | 'description' | 'status' | 'priority' | 'work_days' | 'notes'>
export interface MeetingAssignment { user_id: number; status: string | null; person?: MeetingPerson }
export interface MeetingTask { assignments?: MeetingAssignment[]; id?: number; position?: number; name: string; status: string | null }
export type MeetingPerson = Pick<User, 'id' | 'username' | 'display_name'>
export interface Meeting { revision?: number; id: number; meeting_date: string; meeting_type: string; content: string; needs_follow_up: boolean; creator: MeetingPerson | null; updaters: MeetingPerson[]; tasks: MeetingTask[] }
export interface MeetingPage { items: Meeting[]; total: number; page: number; page_size: number }

export interface MessageTarget { date?: string; week?: string; task?: number }
export interface LiveMessage {
  id: number
  kind: '转交任务' | '会议指派' | '代码审查'
  title?: string
  is_read: boolean
  target?: MessageTarget | null
}
export interface ScheduleSettings {
  enabled: boolean
  interval_minutes: number
}
