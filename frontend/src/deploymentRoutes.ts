import type { LocationQueryRaw, RouteRecordRaw } from 'vue-router'

export const deploymentSections = [
  { id: 'overview', name: 'deployments-overview', label: '部署总览' },
  { id: 'plans', name: 'deployments-plans', label: '发版计划' },
  { id: 'memos', name: 'deployments-memos', label: '发版备忘' },
] as const

export type DeploymentSection = typeof deploymentSections[number]['id']

export function deploymentLocation(section: DeploymentSection, query?: LocationQueryRaw) {
  return { name: `deployments-${section}`, query }
}

export const deploymentRoutes: RouteRecordRaw = {
  path: '/deployments',
  children: [
    {
      path: '',
      redirect: ({ query: { tab, ...query }, hash }) => {
        // 旧书签和已发出的任务链接仍可打开对应菜单或计划详情。
        const section = query.plan || tab === 'plans' ? 'plans' : tab === 'memos' ? 'memos' : 'overview'
        return { ...deploymentLocation(section, query), hash }
      },
    },
    ...deploymentSections.map(({ id, name }) => ({ path: id, name, component: { template: '<div />' } })),
  ],
}
