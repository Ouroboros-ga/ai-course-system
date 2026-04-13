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
    url: '/user/info',
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
 */
export function logout() {
  return request({
    url: '/user/logout',
    method: 'post'
  })
}

/**
 * 更新用户信息
 * @param {Object} data - 更新数据
 */
export function updateUserInfo(data) {
  return request({
    url: '/user/update',
    method: 'put',
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

