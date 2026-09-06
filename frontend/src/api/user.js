// user api 接口

import request from '@/utils/request.js'

/**
 * 用户登录
 * @param {Object} data - 登录数据
 * @param {string} data.username - 用户名
 * @param {string} data.password - 密码
 */
// skipAuthErrorHandling：后端用业务 401 表达"用户名密码错误"（HTTP 仍是 200），
// 这属于凭据校验失败而非 token 失效，绝不能触发全局登出；错误由登录表单展示。
export function login(data) {
  return request({
    url: '/user/login',
    method: 'post',
    data,
    skipErrorToast: true,
    skipAuthErrorHandling: true
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
    data,
    skipErrorToast: true,
    skipAuthErrorHandling: true
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
// 与 login/register 同口径：/user/modify 的业务 401 表示原密码/用户名校验失败，
// 不是 token 失效，不做全局登出。
export function updateUserInfo(data) {
  return request({
    url: '/user/modify',
    method: 'post',
    data,
    skipErrorToast: true,
    skipAuthErrorHandling: true
  })
}

export function modify(data) {
  return request({
    url: '/user/modify',
    method: 'post',
    data,
    skipErrorToast: true,
    skipAuthErrorHandling: true
  })
}

// 修改用户名/密码：原密码验证失败时后端返回业务 401（user.py「原密码验证失败」），
// 同样不能触发全局登出——否则改密码输错原密码会被整页踢回登录页。
export function updateMyProfile(data) {
  return request({
    url: '/user/me/profile',
    method: 'patch',
    data,
    skipErrorToast: true,
    skipAuthErrorHandling: true,
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
