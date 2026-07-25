// user api 接口

import request from '@/utils/request.js'

/**
 * 用户登录
 * @param {Object} data - 登录数据
 * @param {string} data.username - 用户名
 * @param {string} data.password - 密码
 */
export function login(data) {
  return request({
    url: '/user/login',
    method: 'post',
    data
  })
}

/**
 * 用户注册
 * @param {Object} data - 注册数据
 * @param {string} data.username - 用户名
 * @param {string} data.password - 密码
 */
export function register(data) {
  return request({
    url: '/user/register',
    method: 'post',
    data
  })
}

/**
 * 获取用户信息
 */
export function getUserInfo() {
  return request({
    url: '/user/me',
    method: 'get'
  })
}

export function getMyInfo() {
  return request({
    url: '/user/me',
    method: 'get'
  })
}

/**
 * 用户退出登录
 *
 * 决策（批次0 API契约清理）：后端为无状态 JWT，不维护 token 黑名单，
 * 因此没有 POST /user/logout 端点。前端退出时直接清除本地 token 与
 * 登录状态即可，不调用后端。已移除原先指向不存在端点的死调用。
 */
/**
 * 更新用户信息
 * @param {Object} data - 更新数据
 */
export function updateUserInfo(data) {
  return request({
    url: '/user/modify',
    method: 'post',
    data
  })
}

export function modify(data) {
  return request({
    url: '/user/modify',
    method: 'post',
    data
  })
}

export function getUserList() {
  return request({
    url: '/user/list',
    method: 'get'
  })
}

export function changeUserRole(data) {
  return request({
    url: '/user/role',
    method: 'put',
    data
  })
}

export function getUserStats() {
  return request({
    url: '/user/stats',
    method: 'get'
  })
}

