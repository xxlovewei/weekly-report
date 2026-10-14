import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import './style.css'

const routes = ['login', 'work', 'reports', 'categories', 'meetings', 'users', 'password'].map(name => ({ path: `/${name}`, name, component: { template: '<div />' } }))
const router = createRouter({ history: createWebHistory(import.meta.env.BASE_URL), routes: [...routes, { path: '/', redirect: '/work' }] })
createApp(App).use(router).mount('#app')
