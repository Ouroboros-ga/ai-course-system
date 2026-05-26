import request from '@/utils/request.js'

export function ssoCallback(ticket, redirectUrl) {
  return request({
    url: '/platform/sso/callback',
    method: 'get',
    params: { ticket, redirect_url: redirectUrl }
  })
}

export function syncUser(data) {
  return request({
    url: '/platform/syncUser',
    method: 'post',
    data
  })
}

export function syncCourse(data) {
  return request({
    url: '/platform/syncCourse',
    method: 'post',
    data
  })
}

export function syncEnrollment(data) {
  return request({
    url: '/platform/syncEnrollment',
    method: 'post',
    data
  })
}

export function getBindStatus(courseId) {
  return request({
    url: `/platform/bind/status/${courseId}`,
    method: 'get'
  })
}

export function unbindCourse(courseId) {
  return request({
    url: `/platform/unbind/${courseId}`,
    method: 'delete'
  })
}

export function getPlatformStatus() {
  return request({
    url: '/platform/status',
    method: 'get'
  })
}
