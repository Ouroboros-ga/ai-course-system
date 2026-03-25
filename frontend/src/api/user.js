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
 * 用户数据修改
 * @param {Object} data - 用户数据修改
 * @param {number} data.id - 用户id
 * @param {string} data.username - 用户名
 * @param {string} data.password - 密码
 */
export function modify(data) {
  return request({
    url: '/user/modify',
    method: 'post',
    data
  })
}

