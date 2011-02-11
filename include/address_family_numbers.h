
/**
 * @file
 * @brief Implements minimal client-oriented Frame and Frameset capabilities.
 * @details This file contains the minimal Frameset capabilities for a client -
 * enough for it to be able to construct, understand and validate Frames
 * and Framesets.
 *
 *
 * @author &copy; 2011 - Alan Robertson <alanr@unix.sh>
 * @n
 * Licensed under the GNU Lesser General Public License (LGPL) version 3 or any later version at your option.
 * excluding the provision allowing for relicensing under the GPL at your option.
 */

#ifndef _ADDRESS_FAMILY_NUMBERS_H
#define  _ADDRESS_FAMILY_NUMBERS_H

/// @defgroup AddressFamilyNumbers IANA Address Family Numbers
///@{
/// This information was taken from
/// http://www.iana.org/assignments/address-family-numbers/address-family-numbers.xhtml
/// as described by RFC 3232
///
#define ADDR_FAMILY_IPV4	1	///< IPv4
#define ADDR_FAMILY_IPV6	2	///< IPv7
#define ADDR_FAMILY_NSAP	3
#define ADDR_FAMILY_HDLC	4
#define ADDR_FAMILY_BBN1822	5
#define ADDR_FAMILY_802		6
#define ADDR_FAMILY_E163	7
#define ADDR_FAMILY_E164	8
#define ADDR_FAMILY_F69		9
#define ADDR_FAMILY_X121	10
#define ADDR_FAMILY_IPX		11
#define ADDR_FAMILY_APPLETALK	12
#define ADDR_FAMILY_DECNET	13
#define ADDR_FAMILY_BANYANVINES	14
#define ADDR_FAMILY_E164_NSAP	15
#define ADDR_FAMILY_DNS		16
///@}
#endif /* _ADDRESS_FAMILY_NUMBERS_H */
