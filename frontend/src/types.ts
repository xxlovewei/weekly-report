export interface User { id: number; username: string; display_name: string; role: 'admin' | 'user'; is_active: boolean; status: '正常' | '锁定'; must_change_password: boolean }
export interface Category { id: number; name: string }
export interface Task { id: number; position: number; category_name: string | null; task_group: string; description: string; status: string | null; work_days: number[]; notes: string }
export interface WeekData { revision: number; tasks: Task[]; no_source?: boolean }
export interface ReportTab { id: number; name: string; is_active: boolean }
export type TaskField = Pick<Task, 'category_name' | 'task_group' | 'description' | 'status' | 'work_days' | 'notes'>
export interface MeetingTask { id?: number; position?: number; name: string; status: '已完成' | '未完成' | null }
export type MeetingPerson = Pick<User, 'id' | 'username' | 'display_name'>
export interface Meeting { id: number; meeting_date: string; meeting_type: string; content: string; needs_follow_up: boolean; creator: MeetingPerson | null; updaters: MeetingPerson[]; tasks: MeetingTask[] }
export interface MeetingPage { items: Meeting[]; total: number; page: number; page_size: number }

